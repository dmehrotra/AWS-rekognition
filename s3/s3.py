#!/usr/bin/env python2
# -*- coding: utf-8 -*-

## --------------------------------------------------------------------
## s3cmd - S3 client
##
## Authors   : Michal Ludvig and contributors
## Copyright : TGRMN Software - http://www.tgrmn.com - and contributors
## Website   : http://s3tools.org
## License   : GPL Version 2
## --------------------------------------------------------------------
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
## --------------------------------------------------------------------

from __future__ import absolute_import, print_function, division

import sys

if float("%d.%d" %(sys.version_info[0], sys.version_info[1])) < 2.6:
    sys.stderr.write(u"ERROR: Python 2.6 or higher required, sorry.\n")
    sys.exit(EX_OSFILE)

import logging
import time
import os
import re
import errno
import glob
import traceback
import codecs
import locale
import subprocess
try:
    import htmlentitydefs
except:
    # python 3 support
    import html.entities as htmlentitydefs

try:
    unicode
except NameError:
    # python 3 support
    # In python 3, unicode -> str, and str -> bytes
    unicode = str

import socket
import shutil
import tempfile

from copy import copy
from optparse import OptionParser, Option, OptionValueError, IndentedHelpFormatter
from logging import debug, info, warning, error

try:
    from shutil import which
except ImportError:
    # python2 fallback code
    from distutils.spawn import find_executable as which

from ssl import SSLError
import io

def output(message):
    sys.stdout.write(message + "\n")
    sys.stdout.flush()

def check_args_type(args, type, verbose_type):
    """NOTE: This function looks like to not be used."""
    for arg in args:
        if S3Uri(arg).type != type:
            raise ParameterError("Expecting %s instead of '%s'" % (verbose_type, arg))

def cmd_du(args):
    s3 = S3(Config())
    if len(args) > 0:
        uri = S3Uri(args[0])
        if uri.type == "s3" and uri.has_bucket():
            subcmd_bucket_usage(s3, uri)
            return EX_OK
    subcmd_bucket_usage_all(s3)
    return EX_OK

def subcmd_bucket_usage_all(s3):
    """
    Returns: sum of bucket sizes as integer
    Raises: S3Error
    """
    cfg = Config()
    response = s3.list_all_buckets()

    buckets_size = 0
    for bucket in response["list"]:
        size = subcmd_bucket_usage(s3, S3Uri("s3://" + bucket["Name"]))
        if size != None:
            buckets_size += size
    total_size, size_coeff = formatSize(buckets_size, cfg.human_readable_sizes)
    total_size_str = str(total_size) + size_coeff
    output(u"".rjust(12, "-"))
    output(u"%s Total" % (total_size_str.ljust(12)))
    return size

def subcmd_bucket_usage(s3, uri):
    """
    Returns: bucket size as integer
    Raises: S3Error
    """
    bucket_size = 0
    object_count = 0
    extra_info = u''

    bucket = uri.bucket()
    prefix = uri.object()
    try:
        for _, _, objects in s3.bucket_list_streaming(bucket, prefix=prefix, recursive=True):
            for obj in objects:
                bucket_size += int(obj["Size"])
                object_count += 1

    except S3Error as e:
        if e.info["Code"] in S3.codes:
            error(S3.codes[e.info["Code"]] % bucket)
        raise

    except KeyboardInterrupt as e:
        extra_info = u' [interrupted]'

    total_size_str = u"%d%s" % formatSize(bucket_size,
                                          Config().human_readable_sizes)
    if Config().human_readable_sizes:
        total_size_str = total_size_str.rjust(5)
    else:
        total_size_str = total_size_str.rjust(12)
    output(u"%s %7s objects %s%s" % (total_size_str, object_count, uri,
                                     extra_info))
    return bucket_size

def cmd_ls(args):
    cfg = Config()
    s3 = S3(cfg)
    if len(args) > 0:
        uri = S3Uri(args[0])
        if uri.type == "s3" and uri.has_bucket():
            subcmd_bucket_list(s3, uri, cfg.limit)
            return EX_OK

    # If not a s3 type uri or no bucket was provided, list all the buckets
    subcmd_all_buckets_list(s3)
    return EX_OK

def subcmd_all_buckets_list(s3):

    response = s3.list_all_buckets()

    for bucket in sorted(response["list"], key=lambda b:b["Name"]):
        output(u"%s  s3://%s" % (formatDateTime(bucket["CreationDate"]),
                                 bucket["Name"]))

def cmd_all_buckets_list_all_content(args):
    cfg = Config()
    s3 = S3(cfg)

    response = s3.list_all_buckets()

    for bucket in response["list"]:
        subcmd_bucket_list(s3, S3Uri("s3://" + bucket["Name"]), cfg.limit)
        output(u"")
    return EX_OK

def subcmd_bucket_list(s3, uri, limit):
    cfg = Config()

    bucket = uri.bucket()
    prefix = uri.object()

    debug(u"Bucket 's3://%s':" % bucket)
    if prefix.endswith('*'):
        prefix = prefix[:-1]
    try:
        response = s3.bucket_list(bucket, prefix = prefix, limit = limit)
    except S3Error as e:
        if e.info["Code"] in S3.codes:
            error(S3.codes[e.info["Code"]] % bucket)
        raise

    # md5 are 32 char long, but for multipart there could be a suffix
    if Config().human_readable_sizes:
        # %(size)5s%(coeff)1s
        format_size = u"%5d%1s"
        dir_str = u"DIR".rjust(6)
    else:
        format_size = u"%12d%s"
        dir_str = u"DIR".rjust(12)
    if cfg.long_listing:
        format_string = u"%(timestamp)16s %(size)s  %(md5)-35s  %(storageclass)-11s  %(uri)s"
    elif cfg.list_md5:
        format_string = u"%(timestamp)16s %(size)s  %(md5)-35s  %(uri)s"
    else:
        format_string = u"%(timestamp)16s %(size)s  %(uri)s"

    for prefix in response['common_prefixes']:
        output(format_string % {
            "timestamp": "",
            "size": dir_str,
            "md5": "",
            "storageclass": "",
            "uri": uri.compose_uri(bucket, prefix["Prefix"])})

    for object in response["list"]:
        md5 = object.get('ETag', '').strip('"\'')
        storageclass = object.get('StorageClass','')

        if cfg.list_md5:
            if '-' in md5: # need to get md5 from the object
                object_uri = uri.compose_uri(bucket, object["Key"])
                info_response = s3.object_info(S3Uri(object_uri))
                try:
                    md5 = info_response['s3cmd-attrs']['md5']
                except KeyError:
                    pass

        size_and_coeff = formatSize(object["Size"],
                                    Config().human_readable_sizes)
        output(format_string % {
            "timestamp": formatDateTime(object["LastModified"]),
            "size" : format_size % size_and_coeff,
            "md5" : md5,
            "storageclass" : storageclass,
            "uri": uri.compose_uri(bucket, object["Key"]),
            })

    if response["truncated"]:
        warning(u"The list is truncated because the settings limit was reached.")

def cmd_bucket_create(args):
    cfg = Config()
    s3 = S3(cfg)
    for arg in args:
        uri = S3Uri(arg)
        if not uri.type == "s3" or not uri.has_bucket() or uri.has_object():
            raise ParameterError("Expecting S3 URI with just the bucket name set instead of '%s'" % arg)
        try:
            response = s3.bucket_create(uri.bucket(), cfg.bucket_location)
            output(u"Bucket '%s' created" % uri.uri())
        except S3Error as e:
            if e.info["Code"] in S3.codes:
                error(S3.codes[e.info["Code"]] % uri.bucket())
            raise
    return EX_OK

def cmd_website_info(args):
    cfg = Config()
    s3 = S3(cfg)
    for arg in args:
        uri = S3Uri(arg)
        if not uri.type == "s3" or not uri.has_bucket() or uri.has_object():
            raise ParameterError("Expecting S3 URI with just the bucket name set instead of '%s'" % arg)
        try:
            response = s3.website_info(uri, cfg.bucket_location)
            if response:
                output(u"Bucket %s: Website configuration" % uri.uri())
                output(u"Website endpoint: %s" % response['website_endpoint'])
                output(u"Index document:   %s" % response['index_document'])
                output(u"Error document:   %s" % response['error_document'])
            else:
                output(u"Bucket %s: Unable to receive website configuration." % (uri.uri()))
        except S3Error as e:
            if e.info["Code"] in S3.codes:
                error(S3.codes[e.info["Code"]] % uri.bucket())
            raise
    return EX_OK

def cmd_website_create(args):
    cfg = Config()
    s3 = S3(cfg)
    for arg in args:
        uri = S3Uri(arg)
        if not uri.type == "s3" or not uri.has_bucket() or uri.has_object():
            raise ParameterError("Expecting S3 URI with just the bucket name set instead of '%s'" % arg)
        try:
            response = s3.website_create(uri, cfg.bucket_location)
            output(u"Bucket '%s': website configuration created." % (uri.uri()))
        except S3Error as e:
            if e.info["Code"] in S3.codes:
                error(S3.codes[e.info["Code"]] % uri.bucket())
            raise
    return EX_OK

def cmd_website_delete(args):
    cfg = Config()
    s3 = S3(cfg)
    for arg in args:
        uri = S3Uri(arg)
        if not uri.type == "s3" or not uri.has_bucket() or uri.has_object():
            raise ParameterError("Expecting S3 URI with just the bucket name set instead of '%s'" % arg)
        try:
            response = s3.website_delete(uri, cfg.bucket_location)
            output(u"Bucket '%s': website configuration deleted." % (uri.uri()))
        except S3Error as e:
            if e.info["Code"] in S3.codes:
                error(S3.codes[e.info["Code"]] % uri.bucket())
            raise
    return EX_OK

def cmd_expiration_set(args):
    cfg = Config()
    s3 = S3(cfg)
    for arg in args:
        uri = S3Uri(arg)
        if not uri.type == "s3" or not uri.has_bucket() or uri.has_object():
            raise ParameterError("Expecting S3 URI with just the bucket name set instead of '%s'" % arg)
        try:
            response = s3.expiration_set(uri, cfg.bucket_location)
            if response["status"] is 200:
                output(u"Bucket '%s': expiration configuration is set." % (uri.uri()))
            elif response["status"] is 204:
                output(u"Bucket '%s': expiration configuration is deleted." % (uri.uri()))
        except S3Error as e:
            if e.info["Code"] in S3.codes:
                error(S3.codes[e.info["Code"]] % uri.bucket())
            raise
    return EX_OK

def cmd_bucket_delete(args):
    cfg = Config()
    s3 = S3(cfg)

    def _bucket_delete_one(uri, retry=True):
        try:
            response = s3.bucket_delete(uri.bucket())
            output(u"Bucket '%s' removed" % uri.uri())
        except S3Error as e:
            if e.info['Code'] == 'NoSuchBucket':
                if cfg.force:
                    return EX_OK
                else:
                    raise
            if e.info['Code'] == 'BucketNotEmpty' and retry and (cfg.force or cfg.recursive):
                warning(u"Bucket is not empty. Removing all the objects from it first. This may take some time...")
                rc = subcmd_batch_del(uri_str = uri.uri())
                if rc == EX_OK:
                    return _bucket_delete_one(uri, False)
                else:
                    output(u"Bucket was not removed")
            elif e.info["Code"] in S3.codes:
                error(S3.codes[e.info["Code"]] % uri.bucket())
            raise
        return EX_OK

    for arg in args:
        uri = S3Uri(arg)
        if not uri.type == "s3" or not uri.has_bucket() or uri.has_object():
            raise ParameterError("Expecting S3 URI with just the bucket name set instead of '%s'" % arg)
        rc = _bucket_delete_one(uri)
        if rc != EX_OK:
            return rc
    return EX_OK

def cmd_object_put(args):
    cfg = Config()
    s3 = S3(cfg)

    if len(args) == 0:
        raise ParameterError("Nothing to upload. Expecting a local file or directory and a S3 URI destination.")

    ## Normalize URI to convert s3://bkt to s3://bkt/ (trailing slash)
    destination_base_uri = S3Uri(args.pop())
    if destination_base_uri.type != 's3':
        raise ParameterError("Destination must be S3Uri. Got: %s" % destination_base_uri)
    destination_base = destination_base_uri.uri()

    if len(args) == 0:
        raise ParameterError("Nothing to upload. Expecting a local file or directory.")

    local_list, single_file_local, exclude_list, total_size_local = fetch_local_list(args, is_src = True)

    local_count = len(local_list)

    info(u"Summary: %d local files to upload" % local_count)

    if local_count == 0:
        raise ParameterError("Nothing to upload.")

    if local_count > 0:
        if not single_file_local and '-' in local_list.keys():
            raise ParameterError("Cannot specify multiple local files if uploading from '-' (ie stdin)")
        elif single_file_local and local_list.keys()[0] == "-" and destination_base.endswith("/"):
            raise ParameterError("Destination S3 URI must not end with '/' when uploading from stdin.")
        elif not destination_base.endswith("/"):
            if not single_file_local:
                raise ParameterError("Destination S3 URI must end with '/' (ie must refer to a directory on the remote side).")
            local_list[local_list.keys()[0]]['remote_uri'] = destination_base
        else:
            for key in local_list:
                local_list[key]['remote_uri'] = destination_base + key

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % key)
        for key in local_list:
            if key != "-":
                nicekey = local_list[key]['full_name']
            else:
                nicekey = "<stdin>"
            output(u"upload: '%s' -> '%s'" % (nicekey, local_list[key]['remote_uri']))

        warning(u"Exiting now because of --dry-run")
        return EX_OK

    seq = 0
    ret = EX_OK
    for key in local_list:
        seq += 1

        uri_final = S3Uri(local_list[key]['remote_uri'])

        extra_headers = copy(cfg.extra_headers)
        full_name_orig = local_list[key]['full_name']
        full_name = full_name_orig
        seq_label = "[%d of %d]" % (seq, local_count)
        if Config().encrypt:
            gpg_exitcode, full_name, extra_headers["x-amz-meta-s3tools-gpgenc"] = gpg_encrypt(full_name_orig)
        attr_header = _build_attr_header(local_list, key)
        debug(u"attr_header: %s" % attr_header)
        extra_headers.update(attr_header)
        try:
            response = s3.object_put(full_name, uri_final, extra_headers, extra_label = seq_label)
        except S3UploadError as exc:
            error(u"Upload of '%s' failed too many times (Last reason: %s)" % (full_name_orig, exc))
            if cfg.stop_on_error:
                ret = EX_DATAERR
                error(u"Exiting now because of --stop-on-error")
                break
            ret = EX_PARTIAL
            continue
        except InvalidFileError as exc:
            error(u"Upload of '%s' is not possible (Reason: %s)" % (full_name_orig, exc))
            ret = EX_PARTIAL
            if cfg.stop_on_error:
                ret = EX_OSFILE
                error(u"Exiting now because of --stop-on-error")
                break
            continue
        if response is not None:
            speed_fmt = formatSize(response["speed"], human_readable = True, floating_point = True)
            if not Config().progress_meter:
                if full_name_orig != "-":
                    nicekey = full_name_orig
                else:
                    nicekey = "<stdin>"
                output(u"upload: '%s' -> '%s' (%d bytes in %0.1f seconds, %0.2f %sB/s) %s" %
                       (nicekey, uri_final, response["size"], response["elapsed"],
                        speed_fmt[0], speed_fmt[1], seq_label))
        if Config().acl_public:
            output(u"Public URL of the object is: %s" %
                   (uri_final.public_url()))
        if Config().encrypt and full_name != full_name_orig:
            debug(u"Removing temporary encrypted file: %s" % full_name)
            os.remove(deunicodise(full_name))
    return ret

def cmd_object_get(args):
    cfg = Config()
    s3 = S3(cfg)

    ## Check arguments:
    ## if not --recursive:
    ##   - first N arguments must be S3Uri
    ##   - if the last one is S3 make current dir the destination_base
    ##   - if the last one is a directory:
    ##       - take all 'basenames' of the remote objects and
    ##         make the destination name be 'destination_base'+'basename'
    ##   - if the last one is a file or not existing:
    ##       - if the number of sources (N, above) == 1 treat it
    ##         as a filename and save the object there.
    ##       - if there's more sources -> Error
    ## if --recursive:
    ##   - first N arguments must be S3Uri
    ##       - for each Uri get a list of remote objects with that Uri as a prefix
    ##       - apply exclude/include rules
    ##       - each list item will have MD5sum, Timestamp and pointer to S3Uri
    ##         used as a prefix.
    ##   - the last arg may be '-' (stdout)
    ##   - the last arg may be a local directory - destination_base
    ##   - if the last one is S3 make current dir the destination_base
    ##   - if the last one doesn't exist check remote list:
    ##       - if there is only one item and its_prefix==its_name
    ##         download that item to the name given in last arg.
    ##       - if there are more remote items use the last arg as a destination_base
    ##         and try to create the directory (incl. all parents).
    ##
    ## In both cases we end up with a list mapping remote object names (keys) to local file names.

    ## Each item will be a dict with the following attributes
    # {'remote_uri', 'local_filename'}
    download_list = []

    if len(args) == 0:
        raise ParameterError("Nothing to download. Expecting S3 URI.")

    if S3Uri(args[-1]).type == 'file':
        destination_base = args.pop()
    else:
        destination_base = "."

    if len(args) == 0:
        raise ParameterError("Nothing to download. Expecting S3 URI.")

    remote_list, exclude_list, remote_total_size = fetch_remote_list(args, require_attribs = False)

    remote_count = len(remote_list)

    info(u"Summary: %d remote files to download" % remote_count)

    if remote_count > 0:
        if destination_base == "-":
            ## stdout is ok for multiple remote files!
            for key in remote_list:
                remote_list[key]['local_filename'] = "-"
        elif not os.path.isdir(deunicodise(destination_base)):
            ## We were either given a file name (existing or not)
            if remote_count > 1:
                raise ParameterError("Destination must be a directory or stdout when downloading multiple sources.")
            remote_list[remote_list.keys()[0]]['local_filename'] = destination_base
        elif os.path.isdir(deunicodise(destination_base)):
            if destination_base[-1] != os.path.sep:
                destination_base += os.path.sep
            for key in remote_list:
                local_filename = destination_base + key
                if os.path.sep != "/":
                    local_filename = os.path.sep.join(local_filename.split("/"))
                remote_list[key]['local_filename'] = local_filename
        else:
            raise InternalError("WTF? Is it a dir or not? -- %s" % destination_base)

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % key)
        for key in remote_list:
            output(u"download: '%s' -> '%s'" % (remote_list[key]['object_uri_str'], remote_list[key]['local_filename']))

        warning(u"Exiting now because of --dry-run")
        return EX_OK

    seq = 0
    ret = EX_OK
    for key in remote_list:
        seq += 1
        item = remote_list[key]
        uri = S3Uri(item['object_uri_str'])
        ## Encode / Decode destination with "replace" to make sure it's compatible with current encoding
        destination = unicodise_safe(item['local_filename'])
        seq_label = "[%d of %d]" % (seq, remote_count)

        start_position = 0

        if destination == "-":
            ## stdout
            dst_stream = io.open(sys.__stdout__.fileno(), mode='wb', closefd=False)
            dst_stream.stream_name = u'<stdout>'
            file_exists = True
        else:
            ## File
            try:
                file_exists = os.path.exists(deunicodise(destination))
                try:
                    dst_stream = io.open(deunicodise(destination), mode='ab')
                    dst_stream.stream_name = destination
                except IOError as e:
                    if e.errno == errno.ENOENT:
                        basename = destination[:destination.rindex(os.path.sep)]
                        info(u"Creating directory: %s" % basename)
                        os.makedirs(deunicodise(basename))
                        dst_stream = io.open(deunicodise(destination), mode='ab')
                        dst_stream.stream_name = destination
                    else:
                        raise
                if file_exists:
                    if Config().get_continue:
                        start_position = dst_stream.tell()
                    elif Config().force:
                        start_position = 0
                        dst_stream.seek(0)
                        dst_stream.truncate()
                    elif Config().skip_existing:
                        info(u"Skipping over existing file: %s" % (destination))
                        continue
                    else:
                        dst_stream.close()
                        raise ParameterError(u"File %s already exists. Use either of --force / --continue / --skip-existing or give it a new name." % destination)
            except IOError as e:
                error(u"Skipping %s: %s" % (destination, e.strerror))
                continue
        try:
            try:
                response = s3.object_get(uri, dst_stream, destination, start_position = start_position, extra_label = seq_label)
            finally:
                dst_stream.close()
        except S3DownloadError as e:
            error(u"%s: Skipping that file.  This is usually a transient error, please try again later." % e)
            if not file_exists: # Delete, only if file didn't exist before!
                debug(u"object_get failed for '%s', deleting..." % (destination,))
                os.unlink(deunicodise(destination))
                ret = EX_PARTIAL
                if cfg.stop_on_error:
                    ret = EX_DATAERR
                    break
            continue
        except S3Error as e:
            if not file_exists: # Delete, only if file didn't exist before!
                debug(u"object_get failed for '%s', deleting..." % (destination,))
                os.unlink(deunicodise(destination))
            raise

        if "x-amz-meta-s3tools-gpgenc" in response["headers"]:
            gpg_decrypt(destination, response["headers"]["x-amz-meta-s3tools-gpgenc"])
            response["size"] = os.stat(deunicodise(destination))[6]
        if "last-modified" in response["headers"] and destination != "-":
            last_modified = time.mktime(time.strptime(response["headers"]["last-modified"], "%a, %d %b %Y %H:%M:%S GMT"))
            os.utime(deunicodise(destination), (last_modified, last_modified))
            debug("set mtime to %s" % last_modified)
        if not Config().progress_meter and destination != "-":
            speed_fmt = formatSize(response["speed"], human_readable = True, floating_point = True)
            output(u"download: '%s' -> '%s' (%d bytes in %0.1f seconds, %0.2f %sB/s)" %
                (uri, destination, response["size"], response["elapsed"], speed_fmt[0], speed_fmt[1]))
        if Config().delete_after_fetch:
            s3.object_delete(uri)
            output(u"File '%s' removed after fetch" % (uri))
    return EX_OK

def cmd_object_del(args):
    cfg = Config()
    recursive = cfg.recursive
    for uri_str in args:
        uri = S3Uri(uri_str)
        if uri.type != "s3":
            raise ParameterError("Expecting S3 URI instead of '%s'" % uri_str)
        if not uri.has_object():
            if recursive and not cfg.force:
                raise ParameterError("Please use --force to delete ALL contents of %s" % uri_str)
            elif not recursive:
                raise ParameterError("File name required, not only the bucket name. Alternatively use --recursive")

        if not recursive:
            rc = subcmd_object_del_uri(uri_str)
        elif cfg.exclude or cfg.include or cfg.max_delete > 0:
            # subcmd_batch_del_iterative does not support file exclusion and can't
            # accurately know how many total files will be deleted, so revert to batch delete.
            rc = subcmd_batch_del(uri_str = uri_str)
        else:
            rc = subcmd_batch_del_iterative(uri_str = uri_str)
        if not rc:
            return rc
    return EX_OK

def subcmd_batch_del_iterative(uri_str = None, bucket = None):
    """ Streaming version of batch deletion (doesn't realize whole list in memory before deleting).

    Differences from subcmd_batch_del:
      - Does not obey --exclude directives or obey cfg.max_delete (use subcmd_batch_del in those cases)
    """
    if bucket and uri_str:
        raise ValueError("Pass only one of uri_str or bucket")
    if bucket: # bucket specified
        uri_str = "s3://%s" % bucket
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(uri_str)
    bucket = uri.bucket()

    deleted_bytes = deleted_count = 0

    for _, _, to_delete in s3.bucket_list_streaming(bucket, prefix=uri.object(), recursive=True):
        if not to_delete:
            continue
        if not cfg.dry_run:
            response = s3.object_batch_delete_uri_strs([uri.compose_uri(bucket, item['Key']) for item in to_delete])
        deleted_bytes += sum(int(item["Size"]) for item in to_delete)
        deleted_count += len(to_delete)
        output('\n'.join(u"delete: '%s'" % uri.compose_uri(bucket, p['Key']) for p in to_delete))

    if deleted_count:
        # display summary data of deleted files
        if cfg.stats:
            stats_info = StatsInfo()
            stats_info.files_deleted = deleted_count
            stats_info.size_deleted = deleted_bytes
            output(stats_info.format_output())
        else:
            total_size, size_coeff = formatSize(deleted_bytes, Config().human_readable_sizes)
            total_size_str = str(total_size) + size_coeff
            info(u"Deleted %s objects (%s) from %s" % (deleted_count, total_size_str, uri))
    else:
        warning(u"Remote list is empty.")

    return EX_OK

def subcmd_batch_del(uri_str = None, bucket = None, remote_list = None):
    """
    Returns: EX_OK
    Raises: ValueError
    """
    cfg = Config()
    s3 = S3(cfg)
    def _batch_del(remote_list):
        to_delete = remote_list[:1000]
        remote_list = remote_list[1000:]
        while len(to_delete):
            debug(u"Batch delete %d, remaining %d" % (len(to_delete), len(remote_list)))
            if not cfg.dry_run:
                response = s3.object_batch_delete(to_delete)
            output('\n'.join((u"delete: '%s'" % to_delete[p]['object_uri_str']) for p in to_delete))
            to_delete = remote_list[:1000]
            remote_list = remote_list[1000:]

    if remote_list is not None and len(remote_list) == 0:
        return False

    if len([item for item in [uri_str, bucket, remote_list] if item]) != 1:
        raise ValueError("One and only one of 'uri_str', 'bucket', 'remote_list' can be specified.")

    if bucket: # bucket specified
        uri_str = "s3://%s" % bucket
    if remote_list is None: # uri_str specified
        remote_list, exclude_list, remote_total_size = fetch_remote_list(uri_str, require_attribs = False)

    if len(remote_list) == 0:
        warning(u"Remote list is empty.")
        return EX_OK

    if cfg.max_delete > 0 and len(remote_list) > cfg.max_delete:
        warning(u"delete: maximum requested number of deletes would be exceeded, none performed.")
        return EX_OK

    _batch_del(remote_list)

    if cfg.dry_run:
        warning(u"Exiting now because of --dry-run")
    return EX_OK

def subcmd_object_del_uri(uri_str, recursive = None):
    """
    Returns: True if XXX, False if XXX
    Raises: ValueError
    """
    cfg = Config()
    s3 = S3(cfg)

    if recursive is None:
        recursive = cfg.recursive

    remote_list, exclude_list, remote_total_size = fetch_remote_list(uri_str, require_attribs = False, recursive = recursive)

    remote_count = len(remote_list)

    info(u"Summary: %d remote files to delete" % remote_count)
    if cfg.max_delete > 0 and remote_count > cfg.max_delete:
        warning(u"delete: maximum requested number of deletes would be exceeded, none performed.")
        return False

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % key)
        for key in remote_list:
            output(u"delete: %s" % remote_list[key]['object_uri_str'])

        warning(u"Exiting now because of --dry-run")
        return True

    for key in remote_list:
        item = remote_list[key]
        response = s3.object_delete(S3Uri(item['object_uri_str']))
        output(u"delete: '%s'" % item['object_uri_str'])
    return True

def cmd_object_restore(args):
    cfg = Config()
    s3 = S3(cfg)

    if cfg.restore_days < 1:
        raise ParameterError("You must restore a file for 1 or more days")

    # accept case-insensitive argument but fix it to match S3 API
    if cfg.restore_priority.title() not in ['Standard', 'Expedited', 'Bulk']:
        raise ParameterError("Valid restoration priorities: bulk, standard, expedited")
    else:
        cfg.restore_priority = cfg.restore_priority.title()

    remote_list, exclude_list, remote_total_size = fetch_remote_list(args, require_attribs = False, recursive = cfg.recursive)

    remote_count = len(remote_list)

    info(u"Summary: Restoring %d remote files for %d days at %s priority" % (remote_count, cfg.restore_days, cfg.restore_priority))

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % key)
        for key in remote_list:
            output(u"restore: '%s'" % remote_list[key]['object_uri_str'])

        warning(u"Exiting now because of --dry-run")
        return EX_OK

    for key in remote_list:
        item = remote_list[key]

        uri = S3Uri(item['object_uri_str'])
        if not item['object_uri_str'].endswith("/"):
            try:
                response = s3.object_restore(S3Uri(item['object_uri_str']))
                output(u"restore: '%s'" % item['object_uri_str'])
            except S3Error as e:
                if e.code == "RestoreAlreadyInProgress":
                    warning("%s: %s" % (e.message, item['object_uri_str']))
                else:
                    raise e
        else:
            debug(u"Skipping directory since only files may be restored")
    return EX_OK


def subcmd_cp_mv(args, process_fce, action_str, message):
    cfg = Config()
    if action_str == 'modify':
        if len(args) < 1:
            raise ParameterError("Expecting one or more S3 URIs for " + action_str)
        destination_base = None
    else:
        if len(args) < 2:
            raise ParameterError("Expecting two or more S3 URIs for " + action_str)
        dst_base_uri = S3Uri(args.pop())
        if dst_base_uri.type != "s3":
            raise ParameterError("Destination must be S3 URI. To download a file use 'get' or 'sync'.")
        destination_base = dst_base_uri.uri()

    scoreboard = ExitScoreboard()

    remote_list, exclude_list, remote_total_size = fetch_remote_list(args, require_attribs = False)

    remote_count = len(remote_list)

    info(u"Summary: %d remote files to %s" % (remote_count, action_str))

    if destination_base:
        # Trying to mv dir1/ to dir2 will not pass a test in S3.FileLists,
        # so we don't need to test for it here.
        if not destination_base.endswith('/') \
           and (len(remote_list) > 1 or cfg.recursive):
            raise ParameterError("Destination must be a directory and end with '/' when acting on a folder content or on multiple sources.")

        if cfg.recursive:
            for key in remote_list:
                remote_list[key]['dest_name'] = destination_base + key
        else:
            for key in remote_list:
                if destination_base.endswith("/"):
                    remote_list[key]['dest_name'] = destination_base + key
                else:
                    remote_list[key]['dest_name'] = destination_base
    else:
        for key in remote_list:
            remote_list[key]['dest_name'] = remote_list[key]['object_uri_str']

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % key)
        for key in remote_list:
            output(u"%s: '%s' -> '%s'" % (action_str, remote_list[key]['object_uri_str'], remote_list[key]['dest_name']))

        warning(u"Exiting now because of --dry-run")
        return EX_OK

    seq = 0
    for key in remote_list:
        seq += 1
        seq_label = "[%d of %d]" % (seq, remote_count)

        item = remote_list[key]
        src_uri = S3Uri(item['object_uri_str'])
        dst_uri = S3Uri(item['dest_name'])

        extra_headers = copy(cfg.extra_headers)
        try:
            response = process_fce(src_uri, dst_uri, extra_headers)
            output(message % { "src" : src_uri, "dst" : dst_uri })
            if Config().acl_public:
                info(u"Public URL is: %s" % dst_uri.public_url())
            scoreboard.success()
        except S3Error as e:
            if e.code == "NoSuchKey":
                scoreboard.notfound()
                warning(u"Key not found %s" % item['object_uri_str'])
            else:
                scoreboard.failed()
            if cfg.stop_on_error: break
    return scoreboard.rc()

def cmd_cp(args):
    s3 = S3(Config())
    return subcmd_cp_mv(args, s3.object_copy, "copy", u"remote copy: '%(src)s' -> '%(dst)s'")

def cmd_modify(args):
    s3 = S3(Config())
    return subcmd_cp_mv(args, s3.object_modify, "modify", u"modify: '%(src)s'")

def cmd_mv(args):
    s3 = S3(Config())
    return subcmd_cp_mv(args, s3.object_move, "move", u"move: '%(src)s' -> '%(dst)s'")

def cmd_info(args):
    cfg = Config()
    s3 = S3(cfg)

    while (len(args)):
        uri_arg = args.pop(0)
        uri = S3Uri(uri_arg)
        if uri.type != "s3" or not uri.has_bucket():
            raise ParameterError("Expecting S3 URI instead of '%s'" % uri_arg)

        try:
            if uri.has_object():
                info = s3.object_info(uri)
                output(u"%s (object):" % uri.uri())
                output(u"   File size: %s" % info['headers']['content-length'])
                output(u"   Last mod:  %s" % info['headers']['last-modified'])
                output(u"   MIME type: %s" % info['headers'].get('content-type', 'none'))
                output(u"   Storage:   %s" % info['headers'].get('x-amz-storage-class', 'STANDARD'))
                md5 = info['headers'].get('etag', '').strip('"\'')
                try:
                    md5 = info['s3cmd-attrs']['md5']
                except KeyError:
                    pass
                output(u"   MD5 sum:   %s" % md5)
                if 'x-amz-server-side-encryption' in info['headers']:
                    output(u"   SSE:       %s" % info['headers']['x-amz-server-side-encryption'])
                else:
                    output(u"   SSE:       none")

            else:
                info = s3.bucket_info(uri)
                output(u"%s (bucket):" % uri.uri())
                output(u"   Location:  %s" % info['bucket-location'])
                output(u"   Payer:     %s" % info['requester-pays'])
                expiration = s3.expiration_info(uri, cfg.bucket_location)
                if expiration:
                    expiration_desc = "Expiration Rule: "
                    if expiration['prefix'] == "":
                        expiration_desc += "all objects in this bucket "
                    else:
                        expiration_desc += "objects with key prefix '" + expiration['prefix'] + "' "
                    expiration_desc += "will expire in '"
                    if expiration['days']:
                        expiration_desc += expiration['days'] + "' day(s) after creation"
                    elif expiration['date']:
                        expiration_desc += expiration['date'] + "' "
                    output(u"   %s" % expiration_desc)
                else:
                    output(u"   Expiration Rule: none")

            try:
                policy = s3.get_policy(uri)
                output(u"   Policy:    %s" % policy)
            except S3Error as exc:
                # Ignore the exception and don't fail the info
                # if the server doesn't support setting ACLs
                if exc.status == 403:
                    output(u"   Policy:    Not available: GetPolicy permission is needed to read the policy")
                elif exc.status == 405:
                    output(u"   Policy:    Not available: Only the bucket owner can read the policy")
                elif exc.status not in [404, 501]:
                    raise exc
                else:
                    output(u"   Policy:    none")

            try:
                cors = s3.get_cors(uri)
                output(u"   CORS:      %s" % cors)
            except S3Error as exc:
                # Ignore the exception and don't fail the info
                # if the server doesn't support setting ACLs
                if exc.status not in [404, 501]:
                    raise exc
                output(u"   CORS:      none")

            try:
                acl = s3.get_acl(uri)
                acl_grant_list = acl.getGrantList()
                for grant in acl_grant_list:
                    output(u"   ACL:       %s: %s" % (grant['grantee'], grant['permission']))
                if acl.isAnonRead():
                    output(u"   URL:       %s" % uri.public_url())
            except S3Error as exc:
                # Ignore the exception and don't fail the info
                # if the server doesn't support setting ACLs
                if exc.status not in [404, 501]:
                    raise exc
                else:
                    output(u"   ACL:       none")

            if uri.has_object():
                # Temporary hack for performance + python3 compatibility
                try:
                    # Check python 2 first
                    info_headers_iter = info['headers'].iteritems()
                except:
                    info_headers_iter = info['headers'].items()
                for header, value in info_headers_iter:
                    if header.startswith('x-amz-meta-'):
                        output(u"   %s: %s" % (header, value))

        except S3Error as e:
            if e.info["Code"] in S3.codes:
                error(S3.codes[e.info["Code"]] % uri.bucket())
            raise
    return EX_OK

def filedicts_to_keys(*args):
    keys = set()
    for a in args:
        keys.update(a.keys())
    keys = list(keys)
    keys.sort()
    return keys

def cmd_sync_remote2remote(args):
    cfg = Config()
    s3 = S3(cfg)

    # Normalise s3://uri (e.g. assert trailing slash)
    destination_base = S3Uri(args[-1]).uri()

    destbase_with_source_list = set()
    for source_arg in args[:-1]:
        if source_arg.endswith('/'):
            destbase_with_source_list.add(destination_base)
        else:
            destbase_with_source_list.add(os.path.join(destination_base,
                                                  os.path.basename(source_arg)))

    stats_info = StatsInfo()

    src_list, src_exclude_list, remote_total_size = fetch_remote_list(args[:-1], recursive = True, require_attribs = True)
    dst_list, dst_exclude_list, _ = fetch_remote_list(destbase_with_source_list, recursive = True, require_attribs = True)

    src_count = len(src_list)
    orig_src_count = src_count
    dst_count = len(dst_list)
    deleted_count = 0

    info(u"Found %d source files, %d destination files" % (src_count, dst_count))

    src_list, dst_list, update_list, copy_pairs = compare_filelists(src_list, dst_list, src_remote = True, dst_remote = True)

    src_count = len(src_list)
    update_count = len(update_list)
    dst_count = len(dst_list)

    print(u"Summary: %d source files to copy, %d files at destination to delete" % (src_count + update_count, dst_count))

    ### Populate 'target_uri' only if we've got something to sync from src to dst
    for key in src_list:
        src_list[key]['target_uri'] = destination_base + key
    for key in update_list:
        update_list[key]['target_uri'] = destination_base + key

    if cfg.dry_run:
        keys = filedicts_to_keys(src_exclude_list, dst_exclude_list)
        for key in keys:
            output(u"exclude: %s" % key)
        if cfg.delete_removed:
            for key in dst_list:
                output(u"delete: '%s'" % dst_list[key]['object_uri_str'])
        for key in src_list:
            output(u"remote copy: '%s' -> '%s'" % (src_list[key]['object_uri_str'], src_list[key]['target_uri']))
        for key in update_list:
            output(u"remote copy: '%s' -> '%s'" % (update_list[key]['object_uri_str'], update_list[key]['target_uri']))
        warning(u"Exiting now because of --dry-run")
        return EX_OK

    # if there are copy pairs, we can't do delete_before, on the chance
    # we need one of the to-be-deleted files as a copy source.
    if len(copy_pairs) > 0:
        cfg.delete_after = True

    if cfg.delete_removed and orig_src_count == 0 and len(dst_list) and not cfg.force:
        warning(u"delete: cowardly refusing to delete because no source files were found.  Use --force to override.")
        cfg.delete_removed = False

    # Delete items in destination that are not in source
    if cfg.delete_removed and not cfg.delete_after:
        subcmd_batch_del(remote_list = dst_list)
        deleted_count = len(dst_list)

    def _upload(src_list, seq, src_count):
        file_list = src_list.keys()
        file_list.sort()
        ret = EX_OK
        total_nb_files = 0
        total_size = 0
        for file in file_list:
            seq += 1
            item = src_list[file]
            src_uri = S3Uri(item['object_uri_str'])
            dst_uri = S3Uri(item['target_uri'])
            seq_label = "[%d of %d]" % (seq, src_count)
            extra_headers = copy(cfg.extra_headers)
            try:
                response = s3.object_copy(src_uri, dst_uri, extra_headers)
                output("remote copy: '%(src)s' -> '%(dst)s'" % { "src" : src_uri, "dst" : dst_uri })
                total_nb_files += 1
                total_size += item.get(u'size', 0)
            except S3Error as e:
                ret = EX_PARTIAL
                error("File '%(src)s' could not be copied: %(e)s" % { "src" : src_uri, "e" : e })
                if cfg.stop_on_error:
                    raise
        return ret, seq, total_nb_files, total_size

    # Perform the synchronization of files
    timestamp_start = time.time()
    seq = 0
    ret, seq, nb_files, size = _upload(src_list, seq, src_count + update_count)
    total_files_copied = nb_files
    total_size_copied = size

    status, seq, nb_files, size = _upload(update_list, seq, src_count + update_count)
    if ret == EX_OK:
        ret = status
    total_files_copied += nb_files
    total_size_copied += size


    n_copied, bytes_saved, failed_copy_files = remote_copy(s3, copy_pairs, destination_base, None)
    total_files_copied += n_copied
    total_size_copied += bytes_saved

    #process files not copied
    debug("Process files that were not remote copied")
    failed_copy_count = len (failed_copy_files)
    for key in failed_copy_files:
        failed_copy_files[key]['target_uri'] = destination_base + key
    status, seq, nb_files, size = _upload(failed_copy_files, seq, src_count + update_count + failed_copy_count)
    if ret == EX_OK:
        ret = status
    total_files_copied += nb_files
    total_size_copied += size

    # Delete items in destination that are not in source
    if cfg.delete_removed and cfg.delete_after:
        subcmd_batch_del(remote_list = dst_list)
        deleted_count = len(dst_list)

    stats_info.files = orig_src_count
    stats_info.size = remote_total_size
    stats_info.files_copied = total_files_copied
    stats_info.size_copied = total_size_copied
    stats_info.files_deleted = deleted_count

    total_elapsed = max(1.0, time.time() - timestamp_start)
    outstr = "Done. Copied %d files in %0.1f seconds, %0.2f files/s." % (total_files_copied, total_elapsed, seq / total_elapsed)
    if cfg.stats:
        outstr += stats_info.format_output()
        output(outstr)
    elif seq > 0:
        output(outstr)
    else:
        info(outstr)

    return ret

def cmd_sync_remote2local(args):
    cfg = Config()
    s3 = S3(cfg)

    def _do_deletes(local_list):
        total_size = 0
        if cfg.max_delete > 0 and len(local_list) > cfg.max_delete:
            warning(u"delete: maximum requested number of deletes would be exceeded, none performed.")
            return total_size
        for key in local_list:
            os.unlink(deunicodise(local_list[key]['full_name']))
            output(u"delete: '%s'" % local_list[key]['full_name'])
            total_size += local_list[key].get(u'size', 0)
        return len(local_list), total_size

    destination_base = args[-1]
    source_args = args[:-1]
    fetch_source_args = args[:-1]

    if not destination_base.endswith(os.path.sep):
        if fetch_source_args[0].endswith(u'/') or len(fetch_source_args) > 1:
            raise ParameterError("Destination must be a directory and end with '/' when downloading multiple sources.")

    stats_info = StatsInfo()

    remote_list, src_exclude_list, remote_total_size = fetch_remote_list(fetch_source_args, recursive = True, require_attribs = True)


    # - The source path is either like "/myPath/my_src_folder" and
    # the user want to download this single folder and Optionally only delete
    # things that have been removed inside this folder. For this case, we only
    # have to look inside destination_base/my_src_folder and not at the root of
    # destination_base.
    # - Or like "/myPath/my_src_folder/" and the user want to have the sync
    # with the content of this folder
    destbase_with_source_list = set()
    for source_arg in fetch_source_args:
        if source_arg.endswith('/'):
            if destination_base.endswith(os.path.sep):
                destbase_with_source_list.add(destination_base)
            else:
                destbase_with_source_list.add(destination_base + os.path.sep)
        else:
            destbase_with_source_list.add(os.path.join(destination_base,
                                                      os.path.basename(source_arg)))
    local_list, single_file_local, dst_exclude_list, local_total_size = fetch_local_list(destbase_with_source_list, is_src = False, recursive = True)

    local_count = len(local_list)
    remote_count = len(remote_list)
    orig_remote_count = remote_count

    info(u"Found %d remote files, %d local files" % (remote_count, local_count))

    remote_list, local_list, update_list, copy_pairs = compare_filelists(remote_list, local_list, src_remote = True, dst_remote = False)

    local_count = len(local_list)
    remote_count = len(remote_list)
    update_count = len(update_list)
    copy_pairs_count = len(copy_pairs)

    info(u"Summary: %d remote files to download, %d local files to delete, %d local files to hardlink" % (remote_count + update_count, local_count, copy_pairs_count))

    def _set_local_filename(remote_list, destination_base, source_args):
        if len(remote_list) == 0:
            return

        if destination_base.endswith(os.path.sep):
            if not os.path.exists(deunicodise(destination_base)):
                if not cfg.dry_run:
                    os.makedirs(deunicodise(destination_base))
            if not os.path.isdir(deunicodise(destination_base)):
                raise ParameterError("Destination is not an existing directory")
        elif len(remote_list) == 1 and \
             source_args[0] == remote_list[remote_list.keys()[0]].get(u'object_uri_str', ''):
            if os.path.isdir(deunicodise(destination_base)):
                raise ParameterError("Destination already exists and is a directory")
            remote_list[remote_list.keys()[0]]['local_filename'] = destination_base
            return

        if destination_base[-1] != os.path.sep:
            destination_base += os.path.sep
        for key in remote_list:
            local_filename = destination_base + key
            if os.path.sep != "/":
                local_filename = os.path.sep.join(local_filename.split("/"))
            remote_list[key]['local_filename'] = local_filename

    _set_local_filename(remote_list, destination_base, source_args)
    _set_local_filename(update_list, destination_base, source_args)

    if cfg.dry_run:
        keys = filedicts_to_keys(src_exclude_list, dst_exclude_list)
        for key in keys:
            output(u"exclude: %s" % key)
        if cfg.delete_removed:
            for key in local_list:
                output(u"delete: '%s'" % local_list[key]['full_name'])
        for key in remote_list:
            output(u"download: '%s' -> '%s'" % (remote_list[key]['object_uri_str'], remote_list[key]['local_filename']))
        for key in update_list:
            output(u"download: '%s' -> '%s'" % (update_list[key]['object_uri_str'], update_list[key]['local_filename']))

        warning(u"Exiting now because of --dry-run")
        return EX_OK

    # if there are copy pairs, we can't do delete_before, on the chance
    # we need one of the to-be-deleted files as a copy source.
    if len(copy_pairs) > 0:
        cfg.delete_after = True

    if cfg.delete_removed and orig_remote_count == 0 and len(local_list) and not cfg.force:
        warning(u"delete: cowardly refusing to delete because no source files were found.  Use --force to override.")
        cfg.delete_removed = False

    if cfg.delete_removed and not cfg.delete_after:
        deleted_count, deleted_size = _do_deletes(local_list)
    else:
        deleted_count, deleted_size = (0, 0)

    def _download(remote_list, seq, total, total_size, dir_cache):
        original_umask = os.umask(0);
        os.umask(original_umask);
        file_list = remote_list.keys()
        file_list.sort()
        ret = EX_OK
        for file in file_list:
            seq += 1
            item = remote_list[file]
            uri = S3Uri(item['object_uri_str'])
            dst_file = item['local_filename']
            is_empty_directory = dst_file.endswith('/')
            seq_label = "[%d of %d]" % (seq, total)

            dst_dir = unicodise(os.path.dirname(deunicodise(dst_file)))
            if not dst_dir in dir_cache:
                dir_cache[dst_dir] = Utils.mkdir_with_parents(dst_dir)
            if dir_cache[dst_dir] == False:
                if cfg.stop_on_error:
                    error(u"Exiting now because of --stop-on-error")
                    raise OSError("Download of '%s' failed (Reason: %s destination directory is not writable)" % (file, dst_dir))
                error(u"Download of '%s' failed (Reason: %s destination directory is not writable)" % (file, dst_dir))
                ret = EX_PARTIAL
                continue

            try:
                chkptfname_b = ''
                if not is_empty_directory: # ignore empty directory at S3:
                    debug(u"dst_file=%s" % dst_file)
                    # create temporary files (of type .s3cmd.XXXX.tmp) in the same directory
                    # for downloading and then rename once downloaded
                    # unicode provided to mkstemp argument
                    chkptfd, chkptfname_b = tempfile.mkstemp(u".tmp", u".s3cmd.",
                                                           os.path.dirname(dst_file))
                    with io.open(chkptfd, mode='wb') as dst_stream:
                        dst_stream.stream_name = unicodise(chkptfname_b)
                        debug(u"created chkptfname=%s" % dst_stream.stream_name)
                        response = s3.object_get(uri, dst_stream, dst_file, extra_label = seq_label)

                    # download completed, rename the file to destination
                    if os.name == "nt":
                        # Windows is really a bad OS. Rename can't overwrite an existing file
                        try:
                            os.unlink(deunicodise(dst_file))
                        except OSError:
                            pass
                    os.rename(chkptfname_b, deunicodise(dst_file))
                    debug(u"renamed chkptfname=%s to dst_file=%s" % (dst_stream.stream_name, dst_file))
            except OSError as exc:
                allow_partial = True

                if exc.errno == errno.EISDIR:
                    error(u"Download of '%s' failed (Reason: %s is a directory)" % (file, dst_file))
                elif os.name != "nt" and exc.errno == errno.ETXTBSY:
                    error(u"Download of '%s' failed (Reason: %s is currently open for execute, cannot be overwritten)" % (file, dst_file))
                elif exc.errno == errno.EPERM or exc.errno == errno.EACCES:
                    error(u"Download of '%s' failed (Reason: %s permission denied)" % (file, dst_file))
                elif exc.errno == errno.EBUSY:
                    error(u"Download of '%s' failed (Reason: %s is busy)" % (file, dst_file))
                elif exc.errno == errno.EFBIG:
                    error(u"Download of '%s' failed (Reason: %s is too big)" % (file, dst_file))
                elif exc.errno == errno.ENAMETOOLONG:
                    error(u"Download of '%s' failed (Reason: File Name is too long)" % file)

                elif (exc.errno == errno.ENOSPC or (os.name != "nt" and exc.errno == errno.EDQUOT)):
                    error(u"Download of '%s' failed (Reason: No space left)" % file)
                    allow_partial = False
                else:
                    error(u"Download of '%s' failed (Reason: Unknown OsError %d)" % (file, exc.errno or 0))
                    allow_partial = False

                try:
                    # Try to remove the temp file if it exists
                    if chkptfname_b:
                        os.unlink(chkptfname_b)
                except:
                    pass

                if allow_partial and not cfg.stop_on_error:
                    ret = EX_PARTIAL
                    continue

                ret = EX_OSFILE
                if allow_partial:
                    error(u"Exiting now because of --stop-on-error")
                else:
                    error(u"Exiting now because of fatal error")
                raise
            except S3DownloadError as exc:
                error(u"Download of '%s' failed too many times (Last Reason: %s). "
                      "This is usually a transient error, please try again "
                      "later." % (file, exc))
                try:
                    os.unlink(chkptfname_b)
                except Exception as sub_exc:
                    warning(u"Error deleting temporary file %s (Reason: %s)",
                            (dst_stream.stream_name, sub_exc))
                if cfg.stop_on_error:
                    ret = EX_DATAERR
                    error(u"Exiting now because of --stop-on-error")
                    raise
                ret = EX_PARTIAL
                continue
            except S3Error as exc:
                warning(u"Remote file '%s'. S3Error: %s" % (exc.resource, exc))
                try:
                    os.unlink(chkptfname_b)
                except Exception as sub_exc:
                    warning(u"Error deleting temporary file %s (Reason: %s)",
                            (dst_stream.stream_name, sub_exc))
                if cfg.stop_on_error:
                    raise
                ret = EX_PARTIAL
                continue

            try:
                # set permissions on destination file
                if not is_empty_directory: # a normal file
                    mode = 0o777 - original_umask;
                else: # an empty directory, make them readable/executable
                    mode = 0o775
                debug(u"mode=%s" % oct(mode))
                os.chmod(deunicodise(dst_file), mode);
            except:
                raise

            # because we don't upload empty directories,
            # we can continue the loop here, we won't be setting stat info.
            # if we do start to upload empty directories, we'll have to reconsider this.
            if is_empty_directory:
                continue

            try:
                if 's3cmd-attrs' in response and cfg.preserve_attrs:
                    attrs = response['s3cmd-attrs']
                    if 'mode' in attrs:
                        os.chmod(deunicodise(dst_file), int(attrs['mode']))
                    if 'mtime' in attrs or 'atime' in attrs:
                        mtime = ('mtime' in attrs) and int(attrs['mtime']) or int(time.time())
                        atime = ('atime' in attrs) and int(attrs['atime']) or int(time.time())
                        os.utime(deunicodise(dst_file), (atime, mtime))
                    if 'uid' in attrs and 'gid' in attrs:
                        uid = int(attrs['uid'])
                        gid = int(attrs['gid'])
                        os.lchown(deunicodise(dst_file),uid,gid)
                elif 'last-modified' in response['headers']:
                    last_modified = time.mktime(time.strptime(response["headers"]["last-modified"], "%a, %d %b %Y %H:%M:%S GMT"))
                    os.utime(deunicodise(dst_file), (last_modified, last_modified))
                    debug("set mtime to %s" % last_modified)
            except OSError as e:
                ret = EX_PARTIAL
                if e.errno == errno.EEXIST:
                    warning(u"%s exists - not overwriting" % dst_file)
                    continue
                if e.errno in (errno.EPERM, errno.EACCES):
                    warning(u"%s not writable: %s" % (dst_file, e.strerror))
                    if cfg.stop_on_error:
                        raise e
                    continue
                raise e
            except KeyboardInterrupt:
                warning(u"Exiting after keyboard interrupt")
                return
            except Exception as e:
                ret = EX_PARTIAL
                error(u"%s: %s" % (file, e))
                if cfg.stop_on_error:
                    raise OSError(e)
                continue
            finally:
                try:
                    os.remove(chkptfname_b)
                except:
                    pass

            speed_fmt = formatSize(response["speed"], human_readable = True, floating_point = True)
            if not Config().progress_meter:
                output(u"download: '%s' -> '%s' (%d bytes in %0.1f seconds, %0.2f %sB/s) %s" %
                    (uri, dst_file, response["size"], response["elapsed"], speed_fmt[0], speed_fmt[1],
                    seq_label))
            total_size += response["size"]
            if Config().delete_after_fetch:
                s3.object_delete(uri)
                output(u"File '%s' removed after syncing" % (uri))
        return ret, seq, total_size

    size_transferred = 0
    total_elapsed = 0.0
    timestamp_start = time.time()
    dir_cache = {}
    seq = 0
    ret, seq, size_transferred = _download(remote_list, seq, remote_count + update_count, size_transferred, dir_cache)
    status, seq, size_transferred = _download(update_list, seq, remote_count + update_count, size_transferred, dir_cache)
    if ret == EX_OK:
        ret = status

    n_copies, size_copies, failed_copy_list = local_copy(copy_pairs, destination_base)
    _set_local_filename(failed_copy_list, destination_base, source_args)
    status, seq, size_transferred = _download(failed_copy_list, seq, len(failed_copy_list) + remote_count + update_count, size_transferred, dir_cache)
    if ret == EX_OK:
        ret = status

    if cfg.delete_removed and cfg.delete_after:
        deleted_count, deleted_size = _do_deletes(local_list)

    total_elapsed = max(1.0, time.time() - timestamp_start)
    speed_fmt = formatSize(size_transferred / total_elapsed, human_readable = True, floating_point = True)

    stats_info.files = orig_remote_count
    stats_info.size = remote_total_size
    stats_info.files_transferred = len(failed_copy_list) + remote_count + update_count
    stats_info.size_transferred = size_transferred
    stats_info.files_copied = n_copies
    stats_info.size_copied = size_copies
    stats_info.files_deleted = deleted_count
    stats_info.size_deleted = deleted_size

    # Only print out the result if any work has been done or
    # if the user asked for verbose output
    outstr = "Done. Downloaded %d bytes in %0.1f seconds, %0.2f %sB/s." % (size_transferred, total_elapsed, speed_fmt[0], speed_fmt[1])
    if cfg.stats:
        outstr += stats_info.format_output()
        output(outstr)
    elif size_transferred > 0:
        output(outstr)
    else:
        info(outstr)

    return ret

def local_copy(copy_pairs, destination_base):
    # Do NOT hardlink local files by default, that'd be silly
    # For instance all empty files would become hardlinked together!
    saved_bytes = 0
    failed_copy_list = FileDict()
    for (src_obj, dst1, relative_file) in copy_pairs:
        src_file = os.path.join(destination_base, dst1)
        dst_file = os.path.join(destination_base, relative_file)
        dst_dir = os.path.dirname(deunicodise(dst_file))
        try:
            if not os.path.isdir(deunicodise(dst_dir)):
                debug("MKDIR %s" % dst_dir)
                os.makedirs(deunicodise(dst_dir))
            debug(u"Copying %s to %s" % (src_file, dst_file))
            shutil.copy2(deunicodise(src_file), deunicodise(dst_file))
            saved_bytes += src_obj.get(u'size', 0)
        except (IOError, OSError) as e:
            warning(u'Unable to copy or hardlink files %s -> %s (Reason: %s)' % (src_file, dst_file, e))
            failed_copy_list[relative_file] = src_obj
    return len(copy_pairs), saved_bytes, failed_copy_list

def remote_copy(s3, copy_pairs, destination_base, uploaded_objects_list=None):
    cfg = Config()
    saved_bytes = 0
    failed_copy_list = FileDict()
    for (src_obj, dst1, dst2) in copy_pairs:
        debug(u"Remote Copying from %s to %s" % (dst1, dst2))
        dst1_uri = S3Uri(destination_base + dst1)
        dst2_uri = S3Uri(destination_base + dst2)
        extra_headers = copy(cfg.extra_headers)
        try:
            s3.object_copy(dst1_uri, dst2_uri, extra_headers)
            saved_bytes += src_obj.get(u'size', 0)
            output(u"remote copy: '%s' -> '%s'" % (dst1, dst2))
            if uploaded_objects_list is not None:
                uploaded_objects_list.append(dst2)
        except:
            warning(u"Unable to remote copy files '%s' -> '%s'" % (dst1_uri, dst2_uri))
            failed_copy_list[dst2] = src_obj
    return (len(copy_pairs), saved_bytes, failed_copy_list)

def _build_attr_header(local_list, src):
    cfg = Config()
    attrs = {}
    if cfg.preserve_attrs:
        for attr in cfg.preserve_attrs_list:
            if attr == 'uname':
                try:
                    val = Utils.urlencode_string(Utils.getpwuid_username(local_list[src]['uid']), unicode_output=True)
                except (KeyError, TypeError):
                    attr = "uid"
                    val = local_list[src].get('uid')
                    if val:
                        warning(u"%s: Owner username not known. Storing UID=%d instead." % (src, val))
            elif attr == 'gname':
                try:
                    val = Utils.urlencode_string(Utils.getgrgid_grpname(local_list[src].get('gid')), unicode_output=True)
                except (KeyError, TypeError):
                    attr = "gid"
                    val = local_list[src].get('gid')
                    if val:
                        warning(u"%s: Owner groupname not known. Storing GID=%d instead." % (src, val))
            elif attr != "md5":
                try:
                    val = getattr(local_list[src]['sr'], 'st_' + attr)
                except:
                    val = None
            if val is not None:
                attrs[attr] = val

    if 'md5' in cfg.preserve_attrs_list:
        try:
            val = local_list.get_md5(src)
            if val is not None:
                attrs['md5'] = val
        except IOError:
            pass

    if attrs:
        result = ""
        for k in sorted(attrs.keys()):
            result += "%s:%s/" % (k, attrs[k])
        return {'x-amz-meta-s3cmd-attrs' : result[:-1]}
    else:
        return {}


def cmd_sync_local2remote(args):
    cfg = Config()
    s3 = S3(cfg)

    def _single_process(source_args):
        for dest in destinations:
            ## Normalize URI to convert s3://bkt to s3://bkt/ (trailing slash)
            destination_base_uri = S3Uri(dest)
            if destination_base_uri.type != 's3':
                raise ParameterError("Destination must be S3Uri. Got: %s" % destination_base_uri)
            destination_base = destination_base_uri.uri()
        return _child(destination_base, source_args)

    def _parent(source_args):
        # Now that we've done all the disk I/O to look at the local file system and
        # calculate the md5 for each file, fork for each destination to upload to them separately
        # and in parallel
        child_pids = []
        ret = EX_OK

        for dest in destinations:
            ## Normalize URI to convert s3://bkt to s3://bkt/ (trailing slash)
            destination_base_uri = S3Uri(dest)
            if destination_base_uri.type != 's3':
                raise ParameterError("Destination must be S3Uri. Got: %s" % destination_base_uri)
            destination_base = destination_base_uri.uri()
            child_pid = os.fork()
            if child_pid == 0:
                os._exit(_child(destination_base, source_args))
            else:
                child_pids.append(child_pid)

        while len(child_pids):
            (pid, status) = os.wait()
            child_pids.remove(pid)
            if ret == EX_OK:
                ret = os.WEXITSTATUS(status)

        return ret

    def _child(destination_base, source_args):
        def _set_remote_uri(local_list, destination_base, single_file_local):
            if len(local_list) > 0:
                ## Populate 'remote_uri' only if we've got something to upload
                if not destination_base.endswith("/"):
                    if not single_file_local:
                        raise ParameterError("Destination S3 URI must end with '/' (ie must refer to a directory on the remote side).")
                    local_list[local_list.keys()[0]]['remote_uri'] = destination_base
                else:
                    for key in local_list:
                        local_list[key]['remote_uri'] = destination_base + key

        def _upload(local_list, seq, total, total_size):
            file_list = local_list.keys()
            file_list.sort()
            ret = EX_OK
            for file in file_list:
                seq += 1
                item = local_list[file]
                src = item['full_name']
                uri = S3Uri(item['remote_uri'])
                seq_label = "[%d of %d]" % (seq, total)
                extra_headers = copy(cfg.extra_headers)
                try:
                    attr_header = _build_attr_header(local_list, file)
                    debug(u"attr_header: %s" % attr_header)
                    extra_headers.update(attr_header)
                    response = s3.object_put(src, uri, extra_headers, extra_label = seq_label)
                except S3UploadError as exc:
                    error(u"Upload of '%s' failed too many times (Last reason: %s)" % (item['full_name'], exc))
                    if cfg.stop_on_error:
                        ret = EX_DATAERR
                        error(u"Exiting now because of --stop-on-error")
                        raise
                    ret = EX_PARTIAL
                    continue
                except InvalidFileError as exc:
                    error(u"Upload of '%s' is not possible (Reason: %s)" % (item['full_name'], exc))
                    ret = EX_PARTIAL
                    if cfg.stop_on_error:
                        ret = EX_OSFILE
                        error(u"Exiting now because of --stop-on-error")
                        raise
                    continue
                speed_fmt = formatSize(response["speed"], human_readable = True, floating_point = True)
                if not cfg.progress_meter:
                    output(u"upload: '%s' -> '%s' (%d bytes in %0.1f seconds, %0.2f %sB/s) %s" %
                        (item['full_name'], uri, response["size"], response["elapsed"],
                        speed_fmt[0], speed_fmt[1], seq_label))
                total_size += response["size"]
                uploaded_objects_list.append(uri.object())
            return ret, seq, total_size


        stats_info = StatsInfo()

        local_list, single_file_local, src_exclude_list, local_total_size = fetch_local_list(args[:-1], is_src = True, recursive = True)

        # - The source path is either like "/myPath/my_src_folder" and
        # the user want to upload this single folder and optionally only delete
        # things that have been removed inside this folder. For this case,
        # we only have to look inside destination_base/my_src_folder and not at
        # the root of destination_base.
        # - Or like "/myPath/my_src_folder/" and the user want to have the sync
        # with the content of this folder
        # Special case, "." for current folder.
        destbase_with_source_list = set()
        for source_arg in source_args:
            if not source_arg.endswith('/') and os.path.basename(source_arg) != '.' \
               and not single_file_local:
                destbase_with_source_list.add(os.path.join(destination_base,
                                                    os.path.basename(source_arg)))
            else:
                destbase_with_source_list.add(destination_base)

        remote_list, dst_exclude_list, remote_total_size = fetch_remote_list(destbase_with_source_list, recursive = True, require_attribs = True)

        local_count = len(local_list)
        orig_local_count = local_count
        remote_count = len(remote_list)

        info(u"Found %d local files, %d remote files" % (local_count, remote_count))

        if single_file_local and len(local_list) == 1 and len(remote_list) == 1:
            ## Make remote_key same as local_key for comparison if we're dealing with only one file
            remote_list_entry = remote_list[remote_list.keys()[0]]
            # Flush remote_list, by the way
            remote_list = FileDict()
            remote_list[local_list.keys()[0]] =  remote_list_entry

        local_list, remote_list, update_list, copy_pairs = compare_filelists(local_list, remote_list, src_remote = False, dst_remote = True)

        local_count = len(local_list)
        update_count = len(update_list)
        copy_count = len(copy_pairs)
        remote_count = len(remote_list)
        upload_count = local_count + update_count

        info(u"Summary: %d local files to upload, %d files to remote copy, %d remote files to delete" % (upload_count, copy_count, remote_count))

        _set_remote_uri(local_list, destination_base, single_file_local)
        _set_remote_uri(update_list, destination_base, single_file_local)

        if cfg.dry_run:
            keys = filedicts_to_keys(src_exclude_list, dst_exclude_list)
            for key in keys:
                output(u"exclude: %s" % key)
            for key in local_list:
                output(u"upload: '%s' -> '%s'" % (local_list[key]['full_name'], local_list[key]['remote_uri']))
            for key in update_list:
                output(u"upload: '%s' -> '%s'" % (update_list[key]['full_name'], update_list[key]['remote_uri']))
            for (src_obj, dst1, dst2) in copy_pairs:
                output(u"remote copy: '%s' -> '%s'" % (dst1, dst2))
            if cfg.delete_removed:
                for key in remote_list:
                    output(u"delete: '%s'" % remote_list[key]['object_uri_str'])

            warning(u"Exiting now because of --dry-run")
            return EX_OK

        # if there are copy pairs, we can't do delete_before, on the chance
        # we need one of the to-be-deleted files as a copy source.
        if len(copy_pairs) > 0:
            cfg.delete_after = True

        if cfg.delete_removed and orig_local_count == 0 and len(remote_list) and not cfg.force:
            warning(u"delete: cowardly refusing to delete because no source files were found.  Use --force to override.")
            cfg.delete_removed = False

        if cfg.delete_removed and not cfg.delete_after and remote_list:
            subcmd_batch_del(remote_list = remote_list)

        size_transferred = 0
        total_elapsed = 0.0
        timestamp_start = time.time()
        ret, n, size_transferred = _upload(local_list, 0, upload_count, size_transferred)
        status, n, size_transferred = _upload(update_list, n, upload_count, size_transferred)
        if ret == EX_OK:
            ret = status
        # uploaded_objects_list reference is passed so it can be filled with
        # destination object of succcessful copies so that they can be
        # invalidated by cf
        n_copies, saved_bytes, failed_copy_files  = remote_copy(s3, copy_pairs,
                                                                destination_base,
                                                                uploaded_objects_list)

        #upload file that could not be copied
        debug("Process files that were not remote copied")
        failed_copy_count = len(failed_copy_files)
        _set_remote_uri(failed_copy_files, destination_base, single_file_local)
        status, n, size_transferred = _upload(failed_copy_files, n, upload_count + failed_copy_count, size_transferred)
        if ret == EX_OK:
            ret = status

        if cfg.delete_removed and cfg.delete_after and remote_list:
            subcmd_batch_del(remote_list = remote_list)
        total_elapsed = max(1.0, time.time() - timestamp_start)
        total_speed = total_elapsed and size_transferred / total_elapsed or 0.0
        speed_fmt = formatSize(total_speed, human_readable = True, floating_point = True)


        stats_info.files = orig_local_count
        stats_info.size = local_total_size
        stats_info.files_transferred = upload_count + failed_copy_count
        stats_info.size_transferred = size_transferred
        stats_info.files_copied = n_copies
        stats_info.size_copied = saved_bytes
        stats_info.files_deleted = remote_count


        # Only print out the result if any work has been done or
        # if the user asked for verbose output
        outstr = "Done. Uploaded %d bytes in %0.1f seconds, %0.2f %sB/s." % (size_transferred, total_elapsed, speed_fmt[0], speed_fmt[1])
        if cfg.stats:
            outstr += stats_info.format_output()
            output(outstr)
        elif size_transferred + saved_bytes > 0:
            output(outstr)
        else:
            info(outstr)

        return ret

    def _invalidate_on_cf(destination_base_uri):
        cf = CloudFront(cfg)
        default_index_file = None
        if cfg.invalidate_default_index_on_cf or cfg.invalidate_default_index_root_on_cf:
            info_response = s3.website_info(destination_base_uri, cfg.bucket_location)
            if info_response:
              default_index_file = info_response['index_document']
              if len(default_index_file) < 1:
                  default_index_file = None

        results = cf.InvalidateObjects(destination_base_uri, uploaded_objects_list, default_index_file, cfg.invalidate_default_index_on_cf, cfg.invalidate_default_index_root_on_cf)
        for result in results:
            if result['status'] == 201:
                output(u"Created invalidation request for %d paths" % len(uploaded_objects_list))
                output(u"Check progress with: s3cmd cfinvalinfo cf://%s/%s" % (result['dist_id'], result['request_id']))

    # main execution
    uploaded_objects_list = []

    if cfg.encrypt:
        error(u"S3cmd 'sync' doesn't yet support GPG encryption, sorry.")
        error(u"Either use unconditional 's3cmd put --recursive'")
        error(u"or disable encryption with --no-encrypt parameter.")
        sys.exit(EX_USAGE)

    for arg in args[:-1]:
        if not os.path.exists(deunicodise(arg)):
            raise ParameterError("Invalid source: '%s' is not an existing file or directory" % arg)

    destinations = [args[-1]]
    if cfg.additional_destinations:
        destinations = destinations + cfg.additional_destinations

    if 'fork' not in os.__all__ or len(destinations) < 2:
        ret = _single_process(args[:-1])
        destination_base_uri = S3Uri(destinations[-1])
        if cfg.invalidate_on_cf:
            if len(uploaded_objects_list) == 0:
                info("Nothing to invalidate in CloudFront")
            else:
                _invalidate_on_cf(destination_base_uri)
    else:
        ret = _parent(args[:-1])
        if cfg.invalidate_on_cf:
            error(u"You cannot use both --cf-invalidate and --add-destination.")
            return(EX_USAGE)

    return ret

def cmd_sync(args):
    cfg = Config()
    if (len(args) < 2):
        raise ParameterError("Too few parameters! Expected: %s" % commands['sync']['param'])
    if cfg.delay_updates:
        warning(u"`delay-updates` is obsolete.")

    for arg in args:
        if arg == u'-':
            raise ParameterError("Stdin or stdout ('-') can't be used for a source or a destination with the sync command.")

    if S3Uri(args[0]).type == "file" and S3Uri(args[-1]).type == "s3":
        return cmd_sync_local2remote(args)
    if S3Uri(args[0]).type == "s3" and S3Uri(args[-1]).type == "file":
        return cmd_sync_remote2local(args)
    if S3Uri(args[0]).type == "s3" and S3Uri(args[-1]).type == "s3":
        return cmd_sync_remote2remote(args)
    raise ParameterError("Invalid source/destination: '%s'" % "' '".join(args))

def cmd_setacl(args):
    cfg = Config()
    s3 = S3(cfg)

    set_to_acl = cfg.acl_public and "Public" or "Private"

    if not cfg.recursive:
        old_args = args
        args = []
        for arg in old_args:
            uri = S3Uri(arg)
            if not uri.has_object():
                if cfg.acl_public != None:
                    info("Setting bucket-level ACL for %s to %s" % (uri.uri(), set_to_acl))
                else:
                    info("Setting bucket-level ACL for %s" % (uri.uri()))
                if not cfg.dry_run:
                    update_acl(s3, uri)
            else:
                args.append(arg)

    remote_list, exclude_list, _ = fetch_remote_list(args)

    remote_count = len(remote_list)

    info(u"Summary: %d remote files to update" % remote_count)

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % key)
        for key in remote_list:
            output(u"setacl: '%s'" % remote_list[key]['object_uri_str'])

        warning(u"Exiting now because of --dry-run")
        return EX_OK

    seq = 0
    for key in remote_list:
        seq += 1
        seq_label = "[%d of %d]" % (seq, remote_count)
        uri = S3Uri(remote_list[key]['object_uri_str'])
        update_acl(s3, uri, seq_label)
    return EX_OK

def cmd_setpolicy(args):
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(args[1])
    policy_file = args[0]
    policy = open(deunicodise(policy_file), 'r').read()

    if cfg.dry_run: return EX_OK

    response = s3.set_policy(uri, policy)

    #if retsponse['status'] == 200:
    debug(u"response - %s" % response['status'])
    if response['status'] == 204:
        output(u"%s: Policy updated" % uri)
    return EX_OK

def cmd_delpolicy(args):
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(args[0])
    if cfg.dry_run: return EX_OK

    response = s3.delete_policy(uri)

    #if retsponse['status'] == 200:
    debug(u"response - %s" % response['status'])
    output(u"%s: Policy deleted" % uri)
    return EX_OK

def cmd_setcors(args):
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(args[1])
    cors_file = args[0]
    cors = open(deunicodise(cors_file), 'r').read()

    if cfg.dry_run: return EX_OK

    response = s3.set_cors(uri, cors)

    #if retsponse['status'] == 200:
    debug(u"response - %s" % response['status'])
    if response['status'] == 204:
        output(u"%s: CORS updated" % uri)
    return EX_OK

def cmd_delcors(args):
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(args[0])
    if cfg.dry_run: return EX_OK

    response = s3.delete_cors(uri)

    #if retsponse['status'] == 200:
    debug(u"response - %s" % response['status'])
    output(u"%s: CORS deleted" % uri)
    return EX_OK

def cmd_set_payer(args):
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(args[0])

    if cfg.dry_run: return EX_OK

    response = s3.set_payer(uri)
    if response['status'] == 200:
        output(u"%s: Payer updated" % uri)
        return EX_OK
    else:
        output(u"%s: Payer NOT updated" % uri)
        return EX_CONFLICT

def cmd_setlifecycle(args):
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(args[1])
    lifecycle_policy_file = args[0]
    lifecycle_policy = open(deunicodise(lifecycle_policy_file), 'r').read()

    if cfg.dry_run: return EX_OK

    response = s3.set_lifecycle_policy(uri, lifecycle_policy)

    debug(u"response - %s" % response['status'])
    if response['status'] == 200:
        output(u"%s: Lifecycle Policy updated" % uri)
    return EX_OK

def cmd_getlifecycle(args):
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(args[0])

    response = s3.get_lifecycle_policy(uri)

    output(u"%s" % getPrettyFromXml(response['data']))
    return EX_OK

def cmd_dellifecycle(args):
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(args[0])
    if cfg.dry_run: return EX_OK

    response = s3.delete_lifecycle_policy(uri)

    debug(u"response - %s" % response['status'])
    output(u"%s: Lifecycle Policy deleted" % uri)
    return EX_OK

def cmd_multipart(args):
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(args[0])

    #id = ''
    #if(len(args) > 1): id = args[1]

    response = s3.get_multipart(uri)
    debug(u"response - %s" % response['status'])
    output(u"%s" % uri)
    tree = getTreeFromXml(response['data'])
    debug(parseNodes(tree))
    output(u"Initiated\tPath\tId")
    for mpupload in parseNodes(tree):
        try:
            output("%s\t%s\t%s" % (mpupload['Initiated'], "s3://" + uri.bucket() + "/" + mpupload['Key'], mpupload['UploadId']))
        except KeyError:
            pass
    return EX_OK

def cmd_abort_multipart(args):
    '''{"cmd":"abortmp",   "label":"abort a multipart upload", "param":"s3://BUCKET Id", "func":cmd_abort_multipart, "argc":2},'''
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(args[0])
    id = args[1]
    response = s3.abort_multipart(uri, id)
    debug(u"response - %s" % response['status'])
    output(u"%s" % uri)
    return EX_OK

def cmd_list_multipart(args):
    '''{"cmd":"abortmp",   "label":"list a multipart upload", "param":"s3://BUCKET Id", "func":cmd_list_multipart, "argc":2},'''
    cfg = Config()
    s3 = S3(cfg)
    uri = S3Uri(args[0])
    id = args[1]

    response = s3.list_multipart(uri, id)
    debug(u"response - %s" % response['status'])
    tree = getTreeFromXml(response['data'])
    output(u"LastModified\t\t\tPartNumber\tETag\tSize")
    for mpupload in parseNodes(tree):
        try:
            output("%s\t%s\t%s\t%s" % (mpupload['LastModified'], mpupload['PartNumber'], mpupload['ETag'], mpupload['Size']))
        except:
            pass
    return EX_OK

def cmd_accesslog(args):
    cfg = Config()
    s3 = S3(cfg)
    bucket_uri = S3Uri(args.pop())
    if bucket_uri.object():
        raise ParameterError("Only bucket name is required for [accesslog] command")
    if cfg.log_target_prefix == False:
        accesslog, response = s3.set_accesslog(bucket_uri, enable = False)
    elif cfg.log_target_prefix:
        log_target_prefix_uri = S3Uri(cfg.log_target_prefix)
        if log_target_prefix_uri.type != "s3":
            raise ParameterError("--log-target-prefix must be a S3 URI")
        accesslog, response = s3.set_accesslog(bucket_uri, enable = True, log_target_prefix_uri = log_target_prefix_uri, acl_public = cfg.acl_public)
    else:   # cfg.log_target_prefix == None
        accesslog = s3.get_accesslog(bucket_uri)

    output(u"Access logging for: %s" % bucket_uri.uri())
    output(u"   Logging Enabled: %s" % accesslog.isLoggingEnabled())
    if accesslog.isLoggingEnabled():
        output(u"     Target prefix: %s" % accesslog.targetPrefix().uri())
        #output(u"   Public Access:   %s" % accesslog.isAclPublic())
    return EX_OK

def cmd_sign(args):
    string_to_sign = args.pop()
    debug("string-to-sign: %r" % string_to_sign)
    signature = Crypto.sign_string_v2(encode_to_s3(string_to_sign))
    output("Signature: %s" % decode_from_s3(signature))
    return EX_OK

def cmd_signurl(args):
    expiry = args.pop()
    url_to_sign = S3Uri(args.pop())
    if url_to_sign.type != 's3':
        raise ParameterError("Must be S3Uri. Got: %s" % url_to_sign)
    debug("url to sign: %r" % url_to_sign)
    signed_url = Crypto.sign_url_v2(url_to_sign, expiry)
    output(signed_url)
    return EX_OK

def cmd_fixbucket(args):
    def _unescape(text):
        ##
        # Removes HTML or XML character references and entities from a text string.
        #
        # @param text The HTML (or XML) source text.
        # @return The plain text, as a Unicode string, if necessary.
        #
        # From: http://effbot.org/zone/re-sub.htm#unescape-html
        def _unescape_fixup(m):
            text = m.group(0)
            if not 'apos' in htmlentitydefs.name2codepoint:
                htmlentitydefs.name2codepoint['apos'] = ord("'")
            if text[:2] == "&#":
                # character reference
                try:
                    if text[:3] == "&#x":
                        return unichr(int(text[3:-1], 16))
                    else:
                        return unichr(int(text[2:-1]))
                except ValueError:
                    pass
            else:
                # named entity
                try:
                    text = unichr(htmlentitydefs.name2codepoint[text[1:-1]])
                except KeyError:
                    pass
            return text # leave as is
            text = text.encode('ascii', 'xmlcharrefreplace')
        return re.sub("&#?\w+;", _unescape_fixup, text)

    cfg = Config()
    cfg.urlencoding_mode = "fixbucket"
    s3 = S3(cfg)

    count = 0
    for arg in args:
        culprit = S3Uri(arg)
        if culprit.type != "s3":
            raise ParameterError("Expecting S3Uri instead of: %s" % arg)
        response = s3.bucket_list_noparse(culprit.bucket(), culprit.object(), recursive = True)
        r_xent = re.compile("&#x[\da-fA-F]+;")
        keys = re.findall("<Key>(.*?)</Key>", response['data'], re.MULTILINE | re.UNICODE)
        debug("Keys: %r" % keys)
        for key in keys:
            if r_xent.search(key):
                info("Fixing: %s" % key)
                debug("Step 1: Transforming %s" % key)
                key_bin = _unescape(key)
                debug("Step 2:       ... to %s" % key_bin)
                key_new = replace_nonprintables(key_bin)
                debug("Step 3:  ... then to %s" % key_new)
                src = S3Uri("s3://%s/%s" % (culprit.bucket(), key_bin))
                dst = S3Uri("s3://%s/%s" % (culprit.bucket(), key_new))
                if cfg.dry_run:
                    output("[--dry-run] File %r would be renamed to %s" % (key_bin, key_new))
                    continue
                try:
                    resp_move = s3.object_move(src, dst)
                    if resp_move['status'] == 200:
                        output("File '%r' renamed to '%s'" % (key_bin, key_new))
                        count += 1
                    else:
                        error("Something went wrong for: %r" % key)
                        error("Please report the problem to s3tools-bugs@lists.sourceforge.net")
                except S3Error:
                    error("Something went wrong for: %r" % key)
                    error("Please report the problem to s3tools-bugs@lists.sourceforge.net")

    if count > 0:
        warning("Fixed %d files' names. Their ACL were reset to Private." % count)
        warning("Use 's3cmd setacl --acl-public s3://...' to make")
        warning("them publicly readable if required.")
    return EX_OK

def resolve_list(lst, args):
    retval = []
    for item in lst:
        retval.append(item % args)
    return retval

def gpg_command(command, passphrase = ""):
    debug("GPG command: " + " ".join(command))
    command = [deunicodise(cmd_entry) for cmd_entry in command]
    p = subprocess.Popen(command, stdin = subprocess.PIPE, stdout = subprocess.PIPE, stderr = subprocess.STDOUT,
                         close_fds = True)
    p_stdout, p_stderr = p.communicate(deunicodise(passphrase + "\n"))
    debug("GPG output:")
    for line in unicodise(p_stdout).split("\n"):
        debug("GPG: " + line)
    p_exitcode = p.wait()
    return p_exitcode

def gpg_encrypt(filename):
    cfg = Config()
    tmp_filename = Utils.mktmpfile()
    args = {
        "gpg_command" : cfg.gpg_command,
        "passphrase_fd" : "0",
        "input_file" : filename,
        "output_file" : tmp_filename,
    }
    info(u"Encrypting file %s to %s..." % (filename, tmp_filename))
    command = resolve_list(cfg.gpg_encrypt.split(" "), args)
    code = gpg_command(command, cfg.gpg_passphrase)
    return (code, tmp_filename, "gpg")

def gpg_decrypt(filename, gpgenc_header = "", in_place = True):
    cfg = Config()
    tmp_filename = Utils.mktmpfile(filename)
    args = {
        "gpg_command" : cfg.gpg_command,
        "passphrase_fd" : "0",
        "input_file" : filename,
        "output_file" : tmp_filename,
    }
    info(u"Decrypting file %s to %s..." % (filename, tmp_filename))
    command = resolve_list(cfg.gpg_decrypt.split(" "), args)
    code = gpg_command(command, cfg.gpg_passphrase)
    if code == 0 and in_place:
        debug(u"Renaming %s to %s" % (tmp_filename, filename))
        os.unlink(deunicodise(filename))
        os.rename(deunicodise(tmp_filename), deunicodise(filename))
        tmp_filename = filename
    return (code, tmp_filename)

def run_configure(config_file, args):
    cfg = Config()
    options = [
        ("access_key", "Access Key", "Access key and Secret key are your identifiers for Amazon S3. Leave them empty for using the env variables."),
        ("secret_key", "Secret Key"),
        ("bucket_location", "Default Region"),
        ("host_base", "S3 Endpoint", "Use \"s3.amazonaws.com\" for S3 Endpoint and not modify it to the target Amazon S3."),
        ("host_bucket", "DNS-style bucket+hostname:port template for accessing a bucket", "Use \"%(bucket)s.s3.amazonaws.com\" to the target Amazon S3. \"%(bucket)s\" and \"%(location)s\" vars can be used\nif the target S3 system supports dns based buckets."),
        ("gpg_passphrase", "Encryption password", "Encryption password is used to protect your files from reading\nby unauthorized persons while in transfer to S3"),
        ("gpg_command", "Path to GPG program"),
        ("use_https", "Use HTTPS protocol", "When using secure HTTPS protocol all communication with Amazon S3\nservers is protected from 3rd party eavesdropping. This method is\nslower than plain HTTP, and can only be proxied with Python 2.7 or newer"),
        ("proxy_host", "HTTP Proxy server name", "On some networks all internet access must go through a HTTP proxy.\nTry setting it here if you can't connect to S3 directly"),
        ("proxy_port", "HTTP Proxy server port"),
        ]
    ## Option-specfic defaults
    if getattr(cfg, "gpg_command") == "":
        setattr(cfg, "gpg_command", which("gpg"))

    if getattr(cfg, "proxy_host") == "" and os.getenv("http_proxy"):
        autodetected_encoding = locale.getpreferredencoding() or "UTF-8"
        re_match=re.match("(http://)?([^:]+):(\d+)",
                          unicodise_s(os.getenv("http_proxy"), autodetected_encoding))
        if re_match:
            setattr(cfg, "proxy_host", re_match.groups()[1])
            setattr(cfg, "proxy_port", re_match.groups()[2])

    try:
        # Support for python3
        # raw_input only exists in py2 and was renamed to input in py3
        global input
        input = raw_input
    except NameError:
        pass

    try:
        while True:
            output(u"\nEnter new values or accept defaults in brackets with Enter.")
            output(u"Refer to user manual for detailed description of all options.")
            for option in options:
                prompt = option[1]
                ## Option-specific handling
                if option[0] == 'proxy_host' and getattr(cfg, 'use_https') == True and sys.hexversion < 0x02070000:
                    setattr(cfg, option[0], "")
                    continue
                if option[0] == 'proxy_port' and getattr(cfg, 'proxy_host') == "":
                    setattr(cfg, option[0], 0)
                    continue

                try:
                    val = getattr(cfg, option[0])
                    if type(val) is bool:
                        val = val and "Yes" or "No"
                    if val not in (None, ""):
                        prompt += " [%s]" % val
                except AttributeError:
                    pass

                if len(option) >= 3:
                    output(u"\n%s" % option[2])

                val = unicodise_s(input(prompt + ": "))
                if val != "":
                    if type(getattr(cfg, option[0])) is bool:
                        # Turn 'Yes' into True, everything else into False
                        val = val.lower().startswith('y')
                    setattr(cfg, option[0], val)
            output(u"\nNew settings:")
            for option in options:
                output(u"  %s: %s" % (option[1], getattr(cfg, option[0])))
            val = input("\nTest access with supplied credentials? [Y/n] ")
            if val.lower().startswith("y") or val == "":
                try:
                    # Default, we try to list 'all' buckets which requires
                    # ListAllMyBuckets permission
                    if len(args) == 0:
                        output(u"Please wait, attempting to list all buckets...")
                        S3(Config()).bucket_list("", "")
                    else:
                        # If user specified a bucket name directly, we check it and only it.
                        # Thus, access check can succeed even if user only has access to
                        # to a single bucket and not ListAllMyBuckets permission.
                        output(u"Please wait, attempting to list bucket: " + args[0])
                        uri = S3Uri(args[0])
                        if uri.type == "s3" and uri.has_bucket():
                            S3(Config()).bucket_list(uri.bucket(), "")
                        else:
                            raise Exception(u"Invalid bucket uri: " + args[0])

                    output(u"Success. Your access key and secret key worked fine :-)")

                    output(u"\nNow verifying that encryption works...")
                    if not getattr(cfg, "gpg_command") or not getattr(cfg, "gpg_passphrase"):
                        output(u"Not configured. Never mind.")
                    else:
                        if not getattr(cfg, "gpg_command"):
                            raise Exception("Path to GPG program not set")
                        if not os.path.isfile(deunicodise(getattr(cfg, "gpg_command"))):
                            raise Exception("GPG program not found")
                        filename = Utils.mktmpfile()
                        with open(deunicodise(filename), "w") as fp:
                            fp.write(os.sys.copyright)
                        ret_enc = gpg_encrypt(filename)
                        ret_dec = gpg_decrypt(ret_enc[1], ret_enc[2], False)
                        hash = [
                            Utils.hash_file_md5(filename),
                            Utils.hash_file_md5(ret_enc[1]),
                            Utils.hash_file_md5(ret_dec[1]),
                        ]
                        os.unlink(deunicodise(filename))
                        os.unlink(deunicodise(ret_enc[1]))
                        os.unlink(deunicodise(ret_dec[1]))
                        if hash[0] == hash[2] and hash[0] != hash[1]:
                            output ("Success. Encryption and decryption worked fine :-)")
                        else:
                            raise Exception("Encryption verification error.")

                except S3Error as e:
                    error(u"Test failed: %s" % (e))
                    if e.code == "AccessDenied":
                        error(u"Are you sure your keys have s3:ListAllMyBuckets permissions?")
                    val = input("\nRetry configuration? [Y/n] ")
                    if val.lower().startswith("y") or val == "":
                        continue
                except Exception as e:
                    error(u"Test failed: %s" % (e))
                    val = input("\nRetry configuration? [Y/n] ")
                    if val.lower().startswith("y") or val == "":
                        continue


            val = input("\nSave settings? [y/N] ")
            if val.lower().startswith("y"):
                break
            val = input("Retry configuration? [Y/n] ")
            if val.lower().startswith("n"):
                raise EOFError()

        ## Overwrite existing config file, make it user-readable only
        old_mask = os.umask(0o077)
        try:
            os.remove(deunicodise(config_file))
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
        try:
            with io.open(deunicodise(config_file), "w", encoding=cfg.encoding) as fp:
                cfg.dump_config(fp)
        finally:
            os.umask(old_mask)
        output(u"Configuration saved to '%s'" % config_file)

    except (EOFError, KeyboardInterrupt):
        output(u"\nConfiguration aborted. Changes were NOT saved.")
        return

    except IOError as e:
        error(u"Writing config file failed: %s: %s" % (config_file, e.strerror))
        sys.exit(EX_IOERR)

def process_patterns_from_file(fname, patterns_list):
    try:
        fn = open(deunicodise(fname), "rt")
    except IOError as e:
        error(e)
        sys.exit(EX_IOERR)
    for pattern in fn:
        pattern = unicodise(pattern).strip()
        if re.match("^#", pattern) or re.match("^\s*$", pattern):
            continue
        debug(u"%s: adding rule: %s" % (fname, pattern))
        patterns_list.append(pattern)

    return patterns_list

def process_patterns(patterns_list, patterns_from, is_glob, option_txt = ""):
    """
    process_patterns(patterns, patterns_from, is_glob, option_txt = "")
    Process --exclude / --include GLOB and REGEXP patterns.
    'option_txt' is 'exclude' / 'include' / 'rexclude' / 'rinclude'
    Returns: patterns_compiled, patterns_text
    """

    patterns_compiled = []
    patterns_textual = {}

    if patterns_list is None:
        patterns_list = []

    if patterns_from:
        ## Append patterns from glob_from
        for fname in patterns_from:
            debug(u"processing --%s-from %s" % (option_txt, fname))
            patterns_list = process_patterns_from_file(fname, patterns_list)

    for pattern in patterns_list:
        debug(u"processing %s rule: %s" % (option_txt, patterns_list))
        if is_glob:
            pattern = glob.fnmatch.translate(pattern)
        r = re.compile(pattern)
        patterns_compiled.append(r)
        patterns_textual[r] = pattern

    return patterns_compiled, patterns_textual

def get_commands_list():
    return [
    {"cmd":"mb", "label":"Make bucket", "param":"s3://BUCKET", "func":cmd_bucket_create, "argc":1},
    {"cmd":"rb", "label":"Remove bucket", "param":"s3://BUCKET", "func":cmd_bucket_delete, "argc":1},
    {"cmd":"ls", "label":"List objects or buckets", "param":"[s3://BUCKET[/PREFIX]]", "func":cmd_ls, "argc":0},
    {"cmd":"la", "label":"List all object in all buckets", "param":"", "func":cmd_all_buckets_list_all_content, "argc":0},
    {"cmd":"put", "label":"Put file into bucket", "param":"FILE [FILE...] s3://BUCKET[/PREFIX]", "func":cmd_object_put, "argc":2},
    {"cmd":"get", "label":"Get file from bucket", "param":"s3://BUCKET/OBJECT LOCAL_FILE", "func":cmd_object_get, "argc":1},
    {"cmd":"del", "label":"Delete file from bucket", "param":"s3://BUCKET/OBJECT", "func":cmd_object_del, "argc":1},
    {"cmd":"rm", "label":"Delete file from bucket (alias for del)", "param":"s3://BUCKET/OBJECT", "func":cmd_object_del, "argc":1},
    #{"cmd":"mkdir", "label":"Make a virtual S3 directory", "param":"s3://BUCKET/path/to/dir", "func":cmd_mkdir, "argc":1},
    {"cmd":"restore", "label":"Restore file from Glacier storage", "param":"s3://BUCKET/OBJECT", "func":cmd_object_restore, "argc":1},
    {"cmd":"sync", "label":"Synchronize a directory tree to S3 (checks files freshness using size and md5 checksum, unless overridden by options, see below)", "param":"LOCAL_DIR s3://BUCKET[/PREFIX] or s3://BUCKET[/PREFIX] LOCAL_DIR", "func":cmd_sync, "argc":2},
    {"cmd":"du", "label":"Disk usage by buckets", "param":"[s3://BUCKET[/PREFIX]]", "func":cmd_du, "argc":0},
    {"cmd":"info", "label":"Get various information about Buckets or Files", "param":"s3://BUCKET[/OBJECT]", "func":cmd_info, "argc":1},
    {"cmd":"cp", "label":"Copy object", "param":"s3://BUCKET1/OBJECT1 s3://BUCKET2[/OBJECT2]", "func":cmd_cp, "argc":2},
    {"cmd":"modify", "label":"Modify object metadata", "param":"s3://BUCKET1/OBJECT", "func":cmd_modify, "argc":1},
    {"cmd":"mv", "label":"Move object", "param":"s3://BUCKET1/OBJECT1 s3://BUCKET2[/OBJECT2]", "func":cmd_mv, "argc":2},
    {"cmd":"setacl", "label":"Modify Access control list for Bucket or Files", "param":"s3://BUCKET[/OBJECT]", "func":cmd_setacl, "argc":1},

    {"cmd":"setpolicy", "label":"Modify Bucket Policy", "param":"FILE s3://BUCKET", "func":cmd_setpolicy, "argc":2},
    {"cmd":"delpolicy", "label":"Delete Bucket Policy", "param":"s3://BUCKET", "func":cmd_delpolicy, "argc":1},
    {"cmd":"setcors", "label":"Modify Bucket CORS", "param":"FILE s3://BUCKET", "func":cmd_setcors, "argc":2},
    {"cmd":"delcors", "label":"Delete Bucket CORS", "param":"s3://BUCKET", "func":cmd_delcors, "argc":1},

    {"cmd":"payer",     "label":"Modify Bucket Requester Pays policy", "param":"s3://BUCKET", "func":cmd_set_payer, "argc":1},
    {"cmd":"multipart", "label":"Show multipart uploads", "param":"s3://BUCKET [Id]", "func":cmd_multipart, "argc":1},
    {"cmd":"abortmp",   "label":"Abort a multipart upload", "param":"s3://BUCKET/OBJECT Id", "func":cmd_abort_multipart, "argc":2},

    {"cmd":"listmp",    "label":"List parts of a multipart upload", "param":"s3://BUCKET/OBJECT Id", "func":cmd_list_multipart, "argc":2},

    {"cmd":"accesslog", "label":"Enable/disable bucket access logging", "param":"s3://BUCKET", "func":cmd_accesslog, "argc":1},
    {"cmd":"sign", "label":"Sign arbitrary string using the secret key", "param":"STRING-TO-SIGN", "func":cmd_sign, "argc":1},
    {"cmd":"signurl", "label":"Sign an S3 URL to provide limited public access with expiry", "param":"s3://BUCKET/OBJECT <expiry_epoch|+expiry_offset>", "func":cmd_signurl, "argc":2},
    {"cmd":"fixbucket", "label":"Fix invalid file names in a bucket", "param":"s3://BUCKET[/PREFIX]", "func":cmd_fixbucket, "argc":1},

    ## Website commands
    {"cmd":"ws-create", "label":"Create Website from bucket", "param":"s3://BUCKET", "func":cmd_website_create, "argc":1},
    {"cmd":"ws-delete", "label":"Delete Website", "param":"s3://BUCKET", "func":cmd_website_delete, "argc":1},
    {"cmd":"ws-info", "label":"Info about Website", "param":"s3://BUCKET", "func":cmd_website_info, "argc":1},

    ## Lifecycle commands
    {"cmd":"expire", "label":"Set or delete expiration rule for the bucket", "param":"s3://BUCKET", "func":cmd_expiration_set, "argc":1},
    {"cmd":"setlifecycle", "label":"Upload a lifecycle policy for the bucket", "param":"FILE s3://BUCKET", "func":cmd_setlifecycle, "argc":2},
    {"cmd":"getlifecycle", "label":"Get a lifecycle policy for the bucket",    "param":"s3://BUCKET", "func":cmd_getlifecycle, "argc":1},
    {"cmd":"dellifecycle", "label":"Remove a lifecycle policy for the bucket", "param":"s3://BUCKET", "func":cmd_dellifecycle, "argc":1},

    ## CloudFront commands
    {"cmd":"cflist", "label":"List CloudFront distribution points", "param":"", "func":CfCmd.info, "argc":0},
    {"cmd":"cfinfo", "label":"Display CloudFront distribution point parameters", "param":"[cf://DIST_ID]", "func":CfCmd.info, "argc":0},
    {"cmd":"cfcreate", "label":"Create CloudFront distribution point", "param":"s3://BUCKET", "func":CfCmd.create, "argc":1},
    {"cmd":"cfdelete", "label":"Delete CloudFront distribution point", "param":"cf://DIST_ID", "func":CfCmd.delete, "argc":1},
    {"cmd":"cfmodify", "label":"Change CloudFront distribution point parameters", "param":"cf://DIST_ID", "func":CfCmd.modify, "argc":1},
    #{"cmd":"cfinval", "label":"Invalidate CloudFront objects", "param":"s3://BUCKET/OBJECT [s3://BUCKET/OBJECT ...]", "func":CfCmd.invalidate, "argc":1},
    {"cmd":"cfinvalinfo", "label":"Display CloudFront invalidation request(s) status", "param":"cf://DIST_ID[/INVAL_ID]", "func":CfCmd.invalinfo, "argc":1},
    ]

def format_commands(progname, commands_list):
    help = "Commands:\n"
    for cmd in commands_list:
        help += "  %s\n      %s %s %s\n" % (cmd["label"], progname, cmd["cmd"], cmd["param"])
    return help


def update_acl(s3, uri, seq_label=""):
    cfg = Config()
    something_changed = False
    acl = s3.get_acl(uri)
    debug(u"acl: %s - %r" % (uri, acl.grantees))
    if cfg.acl_public == True:
        if acl.isAnonRead():
            info(u"%s: already Public, skipping %s" % (uri, seq_label))
        else:
            acl.grantAnonRead()
            something_changed = True
    elif cfg.acl_public == False:  # we explicitely check for False, because it could be None
        if not acl.isAnonRead():
            info(u"%s: already Private, skipping %s" % (uri, seq_label))
        else:
            acl.revokeAnonRead()
            something_changed = True

    # update acl with arguments
    # grant first and revoke later, because revoke has priority
    if cfg.acl_grants:
        something_changed = True
        for grant in cfg.acl_grants:
            acl.grant(**grant)

    if cfg.acl_revokes:
        something_changed = True
        for revoke in cfg.acl_revokes:
            acl.revoke(**revoke)

    if not something_changed:
        return

    retsponse = s3.set_acl(uri, acl)
    if retsponse['status'] == 200:
        if cfg.acl_public in (True, False):
            set_to_acl = cfg.acl_public and "Public" or "Private"
            output(u"%s: ACL set to %s  %s" % (uri, set_to_acl, seq_label))
        else:
            output(u"%s: ACL updated" % uri)

class OptionMimeType(Option):
    def check_mimetype(option, opt, value):
        if re.compile("^[a-z0-9]+/[a-z0-9+\.-]+(;.*)?$", re.IGNORECASE).match(value):
            return value
        raise OptionValueError("option %s: invalid MIME-Type format: %r" % (opt, value))

class OptionS3ACL(Option):
    def check_s3acl(option, opt, value):
        permissions = ('read', 'write', 'read_acp', 'write_acp', 'full_control', 'all')
        try:
            permission, grantee = re.compile("^(\w+):(.+)$", re.IGNORECASE).match(value).groups()
            if not permission or not grantee:
                raise
            if permission in permissions:
                return { 'name' : grantee, 'permission' : permission.upper() }
            else:
                raise OptionValueError("option %s: invalid S3 ACL permission: %s (valid values: %s)" %
                    (opt, permission, ", ".join(permissions)))
        except:
            raise OptionValueError("option %s: invalid S3 ACL format: %r" % (opt, value))

class OptionAll(OptionMimeType, OptionS3ACL):
    TYPE_CHECKER = copy(Option.TYPE_CHECKER)
    TYPE_CHECKER["mimetype"] = OptionMimeType.check_mimetype
    TYPE_CHECKER["s3acl"] = OptionS3ACL.check_s3acl
    TYPES = Option.TYPES + ("mimetype", "s3acl")

class MyHelpFormatter(IndentedHelpFormatter):
    def format_epilog(self, epilog):
        if epilog:
            return "\n" + epilog + "\n"
        else:
            return ""

def main():
    cfg = Config()
    commands_list = get_commands_list()
    commands = {}

    ## Populate "commands" from "commands_list"
    for cmd in commands_list:
        if 'cmd' in cmd:
            commands[cmd['cmd']] = cmd

    optparser = OptionParser(option_class=OptionAll, formatter=MyHelpFormatter())
    #optparser.disable_interspersed_args()

    autodetected_encoding = locale.getpreferredencoding() or "UTF-8"

    config_file = None
    if os.getenv("S3CMD_CONFIG"):
        config_file = unicodise_s(os.getenv("S3CMD_CONFIG"), autodetected_encoding)
    elif os.name == "nt" and os.getenv("USERPROFILE"):
        config_file = os.path.join(unicodise_s(os.getenv("USERPROFILE"), autodetected_encoding),
                                   os.getenv("APPDATA") and unicodise_s(os.getenv("APPDATA"), autodetected_encoding)
                                   or 'Application Data',
                                   "s3cmd.ini")
    else:
        from os.path import expanduser
        config_file = os.path.join(expanduser("~"), ".s3cfg")

    optparser.set_defaults(config = config_file)

    optparser.add_option(      "--configure", dest="run_configure", action="store_true", help="Invoke interactive (re)configuration tool. Optionally use as '--configure s3://some-bucket' to test access to a specific bucket instead of attempting to list them all.")
    optparser.add_option("-c", "--config", dest="config", metavar="FILE", help="Config file name. Defaults to $HOME/.s3cfg")
    optparser.add_option(      "--dump-config", dest="dump_config", action="store_true", help="Dump current configuration after parsing config files and command line options and exit.")
    optparser.add_option(      "--access_key", dest="access_key", help="AWS Access Key")
    optparser.add_option(      "--secret_key", dest="secret_key", help="AWS Secret Key")
    optparser.add_option(      "--access_token", dest="access_token", help="AWS Access Token")

    optparser.add_option("-n", "--dry-run", dest="dry_run", action="store_true", help="Only show what should be uploaded or downloaded but don't actually do it. May still perform S3 requests to get bucket listings and other information though (only for file transfer commands)")

    optparser.add_option("-s", "--ssl", dest="use_https", action="store_true", help="Use HTTPS connection when communicating with S3. (default)")
    optparser.add_option(      "--no-ssl", dest="use_https", action="store_false", help="Don't use HTTPS.")
    optparser.add_option("-e", "--encrypt", dest="encrypt", action="store_true", help="Encrypt files before uploading to S3.")
    optparser.add_option(      "--no-encrypt", dest="encrypt", action="store_false", help="Don't encrypt files.")
    optparser.add_option("-f", "--force", dest="force", action="store_true", help="Force overwrite and other dangerous operations.")
    optparser.add_option(      "--continue", dest="get_continue", action="store_true", help="Continue getting a partially downloaded file (only for [get] command).")
    optparser.add_option(      "--continue-put", dest="put_continue", action="store_true", help="Continue uploading partially uploaded files or multipart upload parts.  Restarts/parts files that don't have matching size and md5.  Skips files/parts that do.  Note: md5sum checks are not always sufficient to check (part) file equality.  Enable this at your own risk.")
    optparser.add_option(      "--upload-id", dest="upload_id", help="UploadId for Multipart Upload, in case you want continue an existing upload (equivalent to --continue-put) and there are multiple partial uploads.  Use s3cmd multipart [URI] to see what UploadIds are associated with the given URI.")
    optparser.add_option(      "--skip-existing", dest="skip_existing", action="store_true", help="Skip over files that exist at the destination (only for [get] and [sync] commands).")
    optparser.add_option("-r", "--recursive", dest="recursive", action="store_true", help="Recursive upload, download or removal.")
    optparser.add_option(      "--check-md5", dest="check_md5", action="store_true", help="Check MD5 sums when comparing files for [sync]. (default)")
    optparser.add_option(      "--no-check-md5", dest="check_md5", action="store_false", help="Do not check MD5 sums when comparing files for [sync]. Only size will be compared. May significantly speed up transfer but may also miss some changed files.")
    optparser.add_option("-P", "--acl-public", dest="acl_public", action="store_true", help="Store objects with ACL allowing read for anyone.")
    optparser.add_option(      "--acl-private", dest="acl_public", action="store_false", help="Store objects with default ACL allowing access for you only.")
    optparser.add_option(      "--acl-grant", dest="acl_grants", type="s3acl", action="append", metavar="PERMISSION:EMAIL or USER_CANONICAL_ID", help="Grant stated permission to a given amazon user. Permission is one of: read, write, read_acp, write_acp, full_control, all")
    optparser.add_option(      "--acl-revoke", dest="acl_revokes", type="s3acl", action="append", metavar="PERMISSION:USER_CANONICAL_ID", help="Revoke stated permission for a given amazon user. Permission is one of: read, write, read_acp, write_acp, full_control, all")

    optparser.add_option("-D", "--restore-days", dest="restore_days", action="store", help="Number of days to keep restored file available (only for 'restore' command).", metavar="NUM")
    optparser.add_option(      "--restore-priority", dest="restore_priority", action="store", choices=['standard', 'expedited', 'bulk'], help="Priority for restoring files from S3 Glacier (only for 'restore' command). Choices available: bulk, standard, expedited")

    optparser.add_option(      "--delete-removed", dest="delete_removed", action="store_true", help="Delete destination objects with no corresponding source file [sync]")
    optparser.add_option(      "--no-delete-removed", dest="delete_removed", action="store_false", help="Don't delete destination objects.")
    optparser.add_option(      "--delete-after", dest="delete_after", action="store_true", help="Perform deletes AFTER new uploads when delete-removed is enabled [sync]")
    optparser.add_option(      "--delay-updates", dest="delay_updates", action="store_true", help="*OBSOLETE* Put all updated files into place at end [sync]")  # OBSOLETE
    optparser.add_option(      "--max-delete", dest="max_delete", action="store", help="Do not delete more than NUM files. [del] and [sync]", metavar="NUM")
    optparser.add_option(      "--limit", dest="limit", action="store", help="Limit number of objects returned in the response body (only for [ls] and [la] commands)", metavar="NUM")
    optparser.add_option(      "--add-destination", dest="additional_destinations", action="append", help="Additional destination for parallel uploads, in addition to last arg.  May be repeated.")
    optparser.add_option(      "--delete-after-fetch", dest="delete_after_fetch", action="store_true", help="Delete remote objects after fetching to local file (only for [get] and [sync] commands).")
    optparser.add_option("-p", "--preserve", dest="preserve_attrs", action="store_true", help="Preserve filesystem attributes (mode, ownership, timestamps). Default for [sync] command.")
    optparser.add_option(      "--no-preserve", dest="preserve_attrs", action="store_false", help="Don't store FS attributes")
    optparser.add_option(      "--exclude", dest="exclude", action="append", metavar="GLOB", help="Filenames and paths matching GLOB will be excluded from sync")
    optparser.add_option(      "--exclude-from", dest="exclude_from", action="append", metavar="FILE", help="Read --exclude GLOBs from FILE")
    optparser.add_option(      "--rexclude", dest="rexclude", action="append", metavar="REGEXP", help="Filenames and paths matching REGEXP (regular expression) will be excluded from sync")
    optparser.add_option(      "--rexclude-from", dest="rexclude_from", action="append", metavar="FILE", help="Read --rexclude REGEXPs from FILE")
    optparser.add_option(      "--include", dest="include", action="append", metavar="GLOB", help="Filenames and paths matching GLOB will be included even if previously excluded by one of --(r)exclude(-from) patterns")
    optparser.add_option(      "--include-from", dest="include_from", action="append", metavar="FILE", help="Read --include GLOBs from FILE")
    optparser.add_option(      "--rinclude", dest="rinclude", action="append", metavar="REGEXP", help="Same as --include but uses REGEXP (regular expression) instead of GLOB")
    optparser.add_option(      "--rinclude-from", dest="rinclude_from", action="append", metavar="FILE", help="Read --rinclude REGEXPs from FILE")

    optparser.add_option(      "--files-from", dest="files_from", action="append", metavar="FILE", help="Read list of source-file names from FILE. Use - to read from stdin.")
    optparser.add_option(      "--region", "--bucket-location", metavar="REGION", dest="bucket_location", help="Region to create bucket in. As of now the regions are: us-east-1, us-west-1, us-west-2, eu-west-1, eu-central-1, ap-northeast-1, ap-southeast-1, ap-southeast-2, sa-east-1")
    optparser.add_option(      "--host", metavar="HOSTNAME", dest="host_base", help="HOSTNAME:PORT for S3 endpoint (default: %s, alternatives such as s3-eu-west-1.amazonaws.com). You should also set --host-bucket." % (cfg.host_base))
    optparser.add_option(      "--host-bucket", dest="host_bucket", help="DNS-style bucket+hostname:port template for accessing a bucket (default: %s)" % (cfg.host_bucket))
    optparser.add_option(      "--reduced-redundancy", "--rr", dest="reduced_redundancy", action="store_true", help="Store object with 'Reduced redundancy'. Lower per-GB price. [put, cp, mv]")
    optparser.add_option(      "--no-reduced-redundancy", "--no-rr", dest="reduced_redundancy", action="store_false", help="Store object without 'Reduced redundancy'. Higher per-GB price. [put, cp, mv]")
    optparser.add_option(      "--storage-class", dest="storage_class", action="store", metavar="CLASS", help="Store object with specified CLASS (STANDARD, STANDARD_IA, or REDUCED_REDUNDANCY). Lower per-GB price. [put, cp, mv]")
    optparser.add_option(      "--access-logging-target-prefix", dest="log_target_prefix", help="Target prefix for access logs (S3 URI) (for [cfmodify] and [accesslog] commands)")
    optparser.add_option(      "--no-access-logging", dest="log_target_prefix", action="store_false", help="Disable access logging (for [cfmodify] and [accesslog] commands)")

    optparser.add_option(      "--default-mime-type", dest="default_mime_type", type="mimetype", action="store", help="Default MIME-type for stored objects. Application default is binary/octet-stream.")
    optparser.add_option("-M", "--guess-mime-type", dest="guess_mime_type", action="store_true", help="Guess MIME-type of files by their extension or mime magic. Fall back to default MIME-Type as specified by --default-mime-type option")
    optparser.add_option(      "--no-guess-mime-type", dest="guess_mime_type", action="store_false", help="Don't guess MIME-type and use the default type instead.")
    optparser.add_option(      "--no-mime-magic", dest="use_mime_magic", action="store_false", help="Don't use mime magic when guessing MIME-type.")
    optparser.add_option("-m", "--mime-type", dest="mime_type", type="mimetype", metavar="MIME/TYPE", help="Force MIME-type. Override both --default-mime-type and --guess-mime-type.")

    optparser.add_option(      "--add-header", dest="add_header", action="append", metavar="NAME:VALUE", help="Add a given HTTP header to the upload request. Can be used multiple times. For instance set 'Expires' or 'Cache-Control' headers (or both) using this option.")
    optparser.add_option(      "--remove-header", dest="remove_headers", action="append", metavar="NAME", help="Remove a given HTTP header.  Can be used multiple times.  For instance, remove 'Expires' or 'Cache-Control' headers (or both) using this option. [modify]")

    optparser.add_option(      "--server-side-encryption", dest="server_side_encryption", action="store_true", help="Specifies that server-side encryption will be used when putting objects. [put, sync, cp, modify]")
    optparser.add_option(      "--server-side-encryption-kms-id", dest="kms_key", action="store", help="Specifies the key id used for server-side encryption with AWS KMS-Managed Keys (SSE-KMS) when putting objects. [put, sync, cp, modify]")

    optparser.add_option(      "--encoding", dest="encoding", metavar="ENCODING", help="Override autodetected terminal and filesystem encoding (character set). Autodetected: %s" % autodetected_encoding)
    optparser.add_option(      "--add-encoding-exts", dest="add_encoding_exts", metavar="EXTENSIONs", help="Add encoding to these comma delimited extensions i.e. (css,js,html) when uploading to S3 )")
    optparser.add_option(      "--verbatim", dest="urlencoding_mode", action="store_const", const="verbatim", help="Use the S3 name as given on the command line. No pre-processing, encoding, etc. Use with caution!")

    optparser.add_option(      "--disable-multipart", dest="enable_multipart", action="store_false", help="Disable multipart upload on files bigger than --multipart-chunk-size-mb")
    optparser.add_option(      "--multipart-chunk-size-mb", dest="multipart_chunk_size_mb", type="int", action="store", metavar="SIZE", help="Size of each chunk of a multipart upload. Files bigger than SIZE are automatically uploaded as multithreaded-multipart, smaller files are uploaded using the traditional method. SIZE is in Mega-Bytes, default chunk size is 15MB, minimum allowed chunk size is 5MB, maximum is 5GB.")

    optparser.add_option(      "--list-md5", dest="list_md5", action="store_true", help="Include MD5 sums in bucket listings (only for 'ls' command).")
    optparser.add_option("-H", "--human-readable-sizes", dest="human_readable_sizes", action="store_true", help="Print sizes in human readable form (eg 1kB instead of 1234).")

    optparser.add_option(      "--ws-index", dest="website_index", action="store", help="Name of index-document (only for [ws-create] command)")
    optparser.add_option(      "--ws-error", dest="website_error", action="store", help="Name of error-document (only for [ws-create] command)")

    optparser.add_option(      "--expiry-date", dest="expiry_date", action="store", help="Indicates when the expiration rule takes effect. (only for [expire] command)")
    optparser.add_option(      "--expiry-days", dest="expiry_days", action="store", help="Indicates the number of days after object creation the expiration rule takes effect. (only for [expire] command)")
    optparser.add_option(      "--expiry-prefix", dest="expiry_prefix", action="store", help="Identifying one or more objects with the prefix to which the expiration rule applies. (only for [expire] command)")

    optparser.add_option(      "--progress", dest="progress_meter", action="store_true", help="Display progress meter (default on TTY).")
    optparser.add_option(      "--no-progress", dest="progress_meter", action="store_false", help="Don't display progress meter (default on non-TTY).")
    optparser.add_option(      "--stats", dest="stats", action="store_true", help="Give some file-transfer stats.")
    optparser.add_option(      "--enable", dest="enable", action="store_true", help="Enable given CloudFront distribution (only for [cfmodify] command)")
    optparser.add_option(      "--disable", dest="enable", action="store_false", help="Disable given CloudFront distribution (only for [cfmodify] command)")
    optparser.add_option(      "--cf-invalidate", dest="invalidate_on_cf", action="store_true", help="Invalidate the uploaded filed in CloudFront. Also see [cfinval] command.")
    # joseprio: adding options to invalidate the default index and the default
    # index root
    optparser.add_option(      "--cf-invalidate-default-index", dest="invalidate_default_index_on_cf", action="store_true", help="When using Custom Origin and S3 static website, invalidate the default index file.")
    optparser.add_option(      "--cf-no-invalidate-default-index-root", dest="invalidate_default_index_root_on_cf", action="store_false", help="When using Custom Origin and S3 static website, don't invalidate the path to the default index file.")
    optparser.add_option(      "--cf-add-cname", dest="cf_cnames_add", action="append", metavar="CNAME", help="Add given CNAME to a CloudFront distribution (only for [cfcreate] and [cfmodify] commands)")
    optparser.add_option(      "--cf-remove-cname", dest="cf_cnames_remove", action="append", metavar="CNAME", help="Remove given CNAME from a CloudFront distribution (only for [cfmodify] command)")
    optparser.add_option(      "--cf-comment", dest="cf_comment", action="store", metavar="COMMENT", help="Set COMMENT for a given CloudFront distribution (only for [cfcreate] and [cfmodify] commands)")
    optparser.add_option(      "--cf-default-root-object", dest="cf_default_root_object", action="store", metavar="DEFAULT_ROOT_OBJECT", help="Set the default root object to return when no object is specified in the URL. Use a relative path, i.e. default/index.html instead of /default/index.html or s3://bucket/default/index.html (only for [cfcreate] and [cfmodify] commands)")
    optparser.add_option("-v", "--verbose", dest="verbosity", action="store_const", const=logging.INFO, help="Enable verbose output.")
    optparser.add_option("-d", "--debug", dest="verbosity", action="store_const", const=logging.DEBUG, help="Enable debug output.")
    optparser.add_option(      "--version", dest="show_version", action="store_true", help="Show s3cmd version (%s) and exit." % (PkgInfo.version))
    optparser.add_option("-F", "--follow-symlinks", dest="follow_symlinks", action="store_true", default=False, help="Follow symbolic links as if they are regular files")
    optparser.add_option(      "--cache-file", dest="cache_file", action="store", default="",  metavar="FILE", help="Cache FILE containing local source MD5 values")
    optparser.add_option("-q", "--quiet", dest="quiet", action="store_true", default=False, help="Silence output on stdout")
    optparser.add_option(      "--ca-certs", dest="ca_certs_file", action="store", default=None, help="Path to SSL CA certificate FILE (instead of system default)")
    optparser.add_option(      "--check-certificate", dest="check_ssl_certificate", action="store_true", help="Check SSL certificate validity")
    optparser.add_option(      "--no-check-certificate", dest="check_ssl_certificate", action="store_false", help="Do not check SSL certificate validity")
    optparser.add_option(      "--check-hostname", dest="check_ssl_hostname", action="store_true", help="Check SSL certificate hostname validity")
    optparser.add_option(      "--no-check-hostname", dest="check_ssl_hostname", action="store_false", help="Do not check SSL certificate hostname validity")
    optparser.add_option(      "--signature-v2", dest="signature_v2", action="store_true", help="Use AWS Signature version 2 instead of newer signature methods. Helpful for S3-like systems that don't have AWS Signature v4 yet.")
    optparser.add_option(      "--limit-rate", dest="limitrate", action="store", type="string", help="Limit the upload or download speed to amount bytes per second.  Amount may be expressed in bytes, kilobytes with the k suffix, or megabytes with the m suffix")
    optparser.add_option(      "--requester-pays", dest="requester_pays", action="store_true", help="Set the REQUESTER PAYS flag for operations")
    optparser.add_option("-l", "--long-listing", dest="long_listing", action="store_true", help="Produce long listing [ls]")
    optparser.add_option(      "--stop-on-error", dest="stop_on_error", action="store_true", help="stop if error in transfer")
    optparser.add_option(      "--content-disposition", dest="content_disposition", action="store", help="Provide a Content-Disposition for signed URLs, e.g., \"inline; filename=myvideo.mp4\"")
    optparser.add_option(      "--content-type", dest="content_type", action="store", help="Provide a Content-Type for signed URLs, e.g., \"video/mp4\"")

    optparser.set_usage(optparser.usage + " COMMAND [parameters]")
    optparser.set_description('S3cmd is a tool for managing objects in '+
        'Amazon S3 storage. It allows for making and removing '+
        '"buckets" and uploading, downloading and removing '+
        '"objects" from these buckets.')
    optparser.epilog = format_commands(optparser.get_prog_name(), commands_list)
    optparser.epilog += ("\nFor more information, updates and news, visit the s3cmd website:\n%s\n" % PkgInfo.url)

    (options, args) = optparser.parse_args()

    ## Some mucking with logging levels to enable
    ## debugging/verbose output for config file parser on request
    logging.basicConfig(level=options.verbosity or Config().verbosity,
                        format='%(levelname)s: %(message)s',
                        stream = sys.stderr)

    if options.show_version:
        output(u"s3cmd version %s" % PkgInfo.version)
        sys.exit(EX_OK)
    debug(u"s3cmd version %s" % PkgInfo.version)

    if options.quiet:
        try:
            f = open("/dev/null", "w")
            sys.stdout = f
        except IOError:
            warning(u"Unable to open /dev/null: --quiet disabled.")

    ## Now finally parse the config file
    if not options.config:
        error(u"Can't find a config file. Please use --config option.")
        sys.exit(EX_CONFIG)

    try:
        cfg = Config(options.config, options.access_key, options.secret_key, options.access_token)
    except ValueError as exc:
        raise ParameterError(unicode(exc))
    except IOError as e:
        if options.run_configure:
            cfg = Config()
        else:
            error(u"%s: %s"  % (options.config, e.strerror))
            error(u"Configuration file not available.")
            error(u"Consider using --configure parameter to create one.")
            sys.exit(EX_CONFIG)

    # allow commandline verbosity config to override config file
    if options.verbosity is not None:
        cfg.verbosity = options.verbosity
    logging.root.setLevel(cfg.verbosity)
    ## Unsupported features on Win32 platform
    if os.name == "nt":
        if cfg.preserve_attrs:
            error(u"Option --preserve is not yet supported on MS Windows platform. Assuming --no-preserve.")
            cfg.preserve_attrs = False
        if cfg.progress_meter:
            error(u"Option --progress is not yet supported on MS Windows platform. Assuming --no-progress.")
            cfg.progress_meter = False

    ## Pre-process --add-header's and put them to Config.extra_headers SortedDict()
    if options.add_header:
        for hdr in options.add_header:
            try:
                key, val = unicodise_s(hdr).split(":", 1)
            except ValueError:
                raise ParameterError("Invalid header format: %s" % unicodise_s(hdr))
            key_inval = re.sub("[a-zA-Z0-9-.]", "", key)
            if key_inval:
                key_inval = key_inval.replace(" ", "<space>")
                key_inval = key_inval.replace("\t", "<tab>")
                raise ParameterError("Invalid character(s) in header name '%s': \"%s\"" % (key, key_inval))
            debug(u"Updating Config.Config extra_headers[%s] -> %s" % (key.replace('_', '-').strip().lower(), val.strip()))
            cfg.extra_headers[key.replace('_', '-').strip().lower()] = val.strip()

    # Process --remove-header
    if options.remove_headers:
        cfg.remove_headers = options.remove_headers

    ## --acl-grant/--acl-revoke arguments are pre-parsed by OptionS3ACL()
    if options.acl_grants:
        for grant in options.acl_grants:
            cfg.acl_grants.append(grant)

    if options.acl_revokes:
        for grant in options.acl_revokes:
            cfg.acl_revokes.append(grant)

    ## Process --(no-)check-md5
    if options.check_md5 == False:
        try:
            cfg.sync_checks.remove("md5")
            cfg.preserve_attrs_list.remove("md5")
        except Exception:
            pass
    if options.check_md5 == True:
        if cfg.sync_checks.count("md5") == 0:
            cfg.sync_checks.append("md5")
        if cfg.preserve_attrs_list.count("md5") == 0:
            cfg.preserve_attrs_list.append("md5")

    ## Update Config with other parameters
    for option in cfg.option_list():
        try:
            value = getattr(options, option)
            if value != None:
                if type(value) == type(b''):
                    value = unicodise_s(value)
                debug(u"Updating Config.Config %s -> %s" % (option, value))
                cfg.update_option(option, value)
        except AttributeError:
            ## Some Config() options are not settable from command line
            pass

    ## Special handling for tri-state options (True, False, None)
    cfg.update_option("enable", options.enable)
    if options.acl_public is not None:
        cfg.update_option("acl_public", options.acl_public)

    ## Check multipart chunk constraints
    if cfg.multipart_chunk_size_mb < MultiPartUpload.MIN_CHUNK_SIZE_MB:
        raise ParameterError("Chunk size %d MB is too small, must be >= %d MB. Please adjust --multipart-chunk-size-mb" % (cfg.multipart_chunk_size_mb, MultiPartUpload.MIN_CHUNK_SIZE_MB))
    if cfg.multipart_chunk_size_mb > MultiPartUpload.MAX_CHUNK_SIZE_MB:
        raise ParameterError("Chunk size %d MB is too large, must be <= %d MB. Please adjust --multipart-chunk-size-mb" % (cfg.multipart_chunk_size_mb, MultiPartUpload.MAX_CHUNK_SIZE_MB))

    ## If an UploadId was provided, set put_continue True
    if options.upload_id:
        cfg.upload_id = options.upload_id
        cfg.put_continue = True

    if cfg.upload_id and not cfg.multipart_chunk_size_mb:
        raise ParameterError("Must have --multipart-chunk-size-mb if using --put-continue or --upload-id")

    ## CloudFront's cf_enable and Config's enable share the same --enable switch
    options.cf_enable = options.enable

    ## CloudFront's cf_logging and Config's log_target_prefix share the same --log-target-prefix switch
    options.cf_logging = options.log_target_prefix

    ## Update CloudFront options if some were set
    for option in CfCmd.options.option_list():
        try:
            value = getattr(options, option)
            if value != None:
                if type(value) == type(b''):
                    value = unicodise_s(value)
            if value != None:
                debug(u"Updating CloudFront.Cmd %s -> %s" % (option, value))
                CfCmd.options.update_option(option, value)
        except AttributeError:
            ## Some CloudFront.Cmd.Options() options are not settable from command line
            pass

    if options.additional_destinations:
        cfg.additional_destinations = options.additional_destinations
    if options.files_from:
        cfg.files_from = options.files_from

    ## Set output and filesystem encoding for printing out filenames.
    try:
        # Support for python3
        # That don't need codecs if output is the
        # encoding of the system, but just in case, still use it.
        # For that, we need to use directly the binary buffer
        # of stdout/stderr
        sys.stdout = codecs.getwriter(cfg.encoding)(sys.stdout.buffer, "replace")
        sys.stderr = codecs.getwriter(cfg.encoding)(sys.stderr.buffer, "replace")
        # getwriter with create an "IObuffer" that have not the encoding attribute
        # better to add it to not break some functions like "input".
        sys.stdout.encoding = cfg.encoding
        sys.stderr.encoding = cfg.encoding
    except AttributeError:
        sys.stdout = codecs.getwriter(cfg.encoding)(sys.stdout, "replace")
        sys.stderr = codecs.getwriter(cfg.encoding)(sys.stderr, "replace")

    ## Process --exclude and --exclude-from
    patterns_list, patterns_textual = process_patterns(options.exclude, options.exclude_from, is_glob = True, option_txt = "exclude")
    cfg.exclude.extend(patterns_list)
    cfg.debug_exclude.update(patterns_textual)

    ## Process --rexclude and --rexclude-from
    patterns_list, patterns_textual = process_patterns(options.rexclude, options.rexclude_from, is_glob = False, option_txt = "rexclude")
    cfg.exclude.extend(patterns_list)
    cfg.debug_exclude.update(patterns_textual)

    ## Process --include and --include-from
    patterns_list, patterns_textual = process_patterns(options.include, options.include_from, is_glob = True, option_txt = "include")
    cfg.include.extend(patterns_list)
    cfg.debug_include.update(patterns_textual)

    ## Process --rinclude and --rinclude-from
    patterns_list, patterns_textual = process_patterns(options.rinclude, options.rinclude_from, is_glob = False, option_txt = "rinclude")
    cfg.include.extend(patterns_list)
    cfg.debug_include.update(patterns_textual)

    ## Set socket read()/write() timeout
    socket.setdefaulttimeout(cfg.socket_timeout)

    if cfg.encrypt and cfg.gpg_passphrase == "":
        error(u"Encryption requested but no passphrase set in config file.")
        error(u"Please re-run 's3cmd --configure' and supply it.")
        sys.exit(EX_CONFIG)

    if options.dump_config:
        cfg.dump_config(sys.stdout)
        sys.exit(EX_OK)

    if options.run_configure:
        # 'args' may contain the test-bucket URI
        run_configure(options.config, args)
        sys.exit(EX_OK)

    ## set config if stop_on_error is set
    if options.stop_on_error:
        cfg.stop_on_error = options.stop_on_error

    if options.content_disposition:
        cfg.content_disposition = options.content_disposition

    if options.content_type:
        cfg.content_type = options.content_type

    if len(args) < 1:
        optparser.print_help()
        sys.exit(EX_USAGE)

    ## Unicodise all remaining arguments:
    args = [unicodise(arg) for arg in args]

    command = args.pop(0)
    try:
        debug(u"Command: %s" % commands[command]["cmd"])
        ## We must do this lookup in extra step to
        ## avoid catching all KeyError exceptions
        ## from inner functions.
        cmd_func = commands[command]["func"]
    except KeyError as e:
        error(u"Invalid command: %s", command)
        sys.exit(EX_USAGE)

    if len(args) < commands[command]["argc"]:
        error(u"Not enough parameters for command '%s'" % command)
        sys.exit(EX_USAGE)

    rc = cmd_func(args)
    if rc is None: # if we missed any cmd_*() returns
        rc = EX_GENERAL
    return rc

def report_exception(e, msg=u''):
        alert_header = u"""
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    An unexpected error has occurred.
  Please try reproducing the error using
  the latest s3cmd code from the git master
  branch found at:
    https://github.com/s3tools/s3cmd
  and have a look at the known issues list:
    https://github.com/s3tools/s3cmd/wiki/Common-known-issues-and-their-solutions
  If the error persists, please report the
  %s (removing any private
  info as necessary) to:
   s3tools-bugs@lists.sourceforge.net%s
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

"""
        sys.stderr.write(alert_header % (u"following lines", u"\n\n" + msg))
        tb = traceback.format_exc()
        try:
            s = u' '.join([unicodise(a) for a in sys.argv])
        except NameError:
            # Error happened before Utils module was yet imported to provide unicodise
            try:
                s = u' '.join([(a) for a in sys.argv])
            except UnicodeDecodeError:
                s = u'[encoding safe] ' + u' '.join([('%r'%a) for a in sys.argv])
        sys.stderr.write(u"Invoked as: %s\n" % s)

        e_class = str(e.__class__)
        e_class = e_class[e_class.rfind(".")+1 : -2]
        try:
            sys.stderr.write(u"Problem: %s: %s\n" % (e_class, e))
        except UnicodeDecodeError:
            sys.stderr.write(u"Problem: [encoding safe] %r: %r\n" % (e_class, e))
        try:
            sys.stderr.write(u"S3cmd:   %s\n" % PkgInfo.version)
        except NameError:
            sys.stderr.write(u"S3cmd:   unknown version. Module import problem?\n")
        sys.stderr.write(u"python:   %s\n" % sys.version)
        try:
            sys.stderr.write(u"environment LANG=%s\n" % unicodise_s(os.getenv("LANG"), 'ascii'))
        except NameError:
            sys.stderr.write(u"environment LANG=%s\n" % os.getenv("LANG"))
        sys.stderr.write(u"\n")
        if type(tb) == unicode:
            sys.stderr.write(tb)
        else:
            sys.stderr.write(unicode(tb, errors="replace"))

        if type(e) == ImportError:
            sys.stderr.write("\n")
            sys.stderr.write("Your sys.path contains these entries:\n")
            for path in sys.path:
                sys.stderr.write(u"\t%s\n" % path)
            sys.stderr.write("Now the question is where have the s3cmd modules been installed?\n")

        sys.stderr.write(alert_header % (u"above lines", u""))

if __name__ == '__main__':
    try:
        ## Our modules
        ## Keep them in try/except block to
        ## detect any syntax errors in there
        from S3.ExitCodes import *
        from S3.Exceptions import *
        from S3 import PkgInfo
        from S3.S3 import S3
        from S3.Config import Config
        from S3.SortedDict import SortedDict
        from S3.FileDict import FileDict
        from S3.S3Uri import S3Uri
        from S3 import Utils
        from S3 import Crypto
        from S3.Utils import *
        from S3.Progress import Progress, StatsInfo
        from S3.CloudFront import Cmd as CfCmd
        from S3.CloudFront import CloudFront
        from S3.FileLists import *
        from S3.MultiPart import MultiPartUpload
    except Exception as e:
        report_exception(e, "Error loading some components of s3cmd (Import Error)")
        # 1 = EX_GENERAL but be safe in that situation
        sys.exit(1)

    try:
        rc = main()
        sys.exit(rc)

    except ImportError as e:
        report_exception(e)
        sys.exit(EX_GENERAL)

    except (ParameterError, InvalidFileError) as e:
        error(u"Parameter problem: %s" % e)
        sys.exit(EX_USAGE)

    except (S3DownloadError, S3UploadError, S3RequestError) as e:
        error(u"S3 Temporary Error: %s.  Please try again later." % e)
        sys.exit(EX_TEMPFAIL)

    except S3Error as e:
        error(u"S3 error: %s" % e)
        sys.exit(e.get_error_code())

    except (S3Exception, S3ResponseError, CloudFrontError) as e:
        report_exception(e)
        sys.exit(EX_SOFTWARE)

    except SystemExit as e:
        sys.exit(e.code)

    except KeyboardInterrupt:
        sys.stderr.write("See ya!\n")
        sys.exit(EX_BREAK)

    except SSLError as e:
        # SSLError is a subtype of IOError
        error("SSL certificate verification failure: %s" % e)
        sys.exit(EX_ACCESSDENIED)

    except socket.gaierror as e:
        # gaierror is a subset of IOError
        # typically encountered error is:
        # gaierror: [Errno -2] Name or service not known
        error(e)
        error("Connection Error: Error resolving a server hostname.\n"
              "Please check the servers address specified in 'host_base', 'host_bucket', 'cloudfront_host', 'website_endpoint'")
        sys.exit(EX_IOERR)

    except IOError as e:
        if e.errno == errno.EPIPE:
            # Fail silently on SIGPIPE. This likely means we wrote to a closed
            # pipe and user does not care for any more output.
            sys.exit(EX_IOERR)

        report_exception(e)
        sys.exit(EX_IOERR)

    except OSError as e:
        error(e)
        sys.exit(EX_OSERR)

    except MemoryError:
        msg = """
MemoryError!  You have exceeded the amount of memory available for this process.
This usually occurs when syncing >750,000 files on a 32-bit python instance.
The solutions to this are:
1) sync several smaller subtrees; or
2) use a 64-bit python on a 64-bit OS with >8GB RAM
        """
        sys.stderr.write(msg)
        sys.exit(EX_OSERR)

    except UnicodeEncodeError as e:
        lang = unicodise_s(os.getenv("LANG"), 'ascii')
        msg = """
You have encountered a UnicodeEncodeError.  Your environment
variable LANG=%s may not specify a Unicode encoding (e.g. UTF-8).
Please set LANG=en_US.UTF-8 or similar in your environment before
invoking s3cmd.
        """ % lang
        report_exception(e, msg)
        sys.exit(EX_GENERAL)

    except Exception as e:
        report_exception(e)
        sys.exit(EX_GENERAL)

# vim:et:ts=4:sts=4:ai
