#!/bin/bash

aws rekognition delete-collection \
    --collection-id "$1"