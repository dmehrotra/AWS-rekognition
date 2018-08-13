#!/bin/bash
aws rekognition create-collection \
    --collection-id "$1"