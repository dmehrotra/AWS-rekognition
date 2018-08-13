#!/bin/bash
aws rekognition index-faces \
      --image '{"S3Object":{"Bucket":"verge.rekognition","Name":"russel/russell4.jpg"}}' \
      --collection-id "russell" \
      --detection-attributes "ALL" \
      --external-image-id "russell4.jpg" 