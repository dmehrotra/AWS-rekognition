import cv2
import sys
import numpy as np
import json

vidcap = cv2.VideoCapture(sys.argv[1])
json_data=open(sys.argv[2]).read()
data = json.loads(json_data)
for d in data:
    if 'personInfo' in d:
        info = "confidence: "+ str(d['personInfo']['Face']['Confidence'])
    else:
        info= "confidence: "+ str(d['faceInfo']['Confidence']) + "( "+ d['faceInfo']['ExternalImageId'] + " )"

    ts = d["TS"]
    awidth=d['boundingBox']['Width']
    atop=d['boundingBox']['Top']
    aleft=d['boundingBox']['Left']
    aheight=d['boundingBox']['Height']

    vidcap.set(cv2.CAP_PROP_POS_MSEC,int(ts))
    hasFrames,image = vidcap.read()
    
    if hasFrames:

        height = image.shape[0]
        width = image.shape[1]
        tx=int(aleft*width)
        ty = int(atop*height)
        bx= int(tx + (awidth*width))
        by = int(ty + (aheight*height))
        cv2.rectangle(image,(tx,ty),(bx,by),(0,255,0),3)
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(image,info,(10,100), font, 1,(255,255,255),2,cv2.LINE_AA)

        cv2.imwrite("frames/russell/"+str(ts)+".jpg", image)     



