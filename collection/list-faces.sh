#!/bin/bash

aws rekognition list-faces \
      --collection-id "$1"  