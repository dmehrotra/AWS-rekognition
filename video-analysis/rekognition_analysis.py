#Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#PDX-License-Identifier: MIT-0 (For details, see https://github.com/awsdocs/amazon-rekognition-developer-guide/blob/master/LICENSE-SAMPLECODE.)



# todo make this write pretty json file
import boto3
import json
import sys


class VideoDetect:
    jobId = ''
    rek = boto3.client('rekognition',region_name='eu-west-1')

    queueUrl = 'https://sqs.eu-west-1.amazonaws.com/382386535927/Rekognition'
    roleArn = 'arn:aws:iam::382386535927:role/ServiceToGiveRekognitionAccessToSNS'
    topicArn = 'arn:aws:sns:eu-west-1:382386535927:AmazonRekognitionRussel'
    bucket = 'verge.rekognition'
    video = 'russel/russell.mp4'

    def main(self):

        jobFound = False
        sqs = boto3.client('sqs')
       

        #=====================================
        response = self.rek.start_face_search(Video={'S3Object':{'Bucket':self.bucket,'Name':self.video}},
            CollectionId='russell',
            NotificationChannel={'RoleArn':self.roleArn, 'SNSTopicArn':self.topicArn})
        #=====================================
        print('Start Job Id: ' + response['JobId'])
        dotLine=0
        while jobFound == False:
            sqsResponse = sqs.receive_message(QueueUrl=self.queueUrl, MessageAttributeNames=['ALL'],
                                          MaxNumberOfMessages=10)

            if sqsResponse:
                if 'Messages' not in sqsResponse:
                    if dotLine<20:
                        
                        dotLine=dotLine+1
                    else:
                       
                        dotLine=0    
                    sys.stdout.flush()
                    continue

                for message in sqsResponse['Messages']:
                    notification = json.loads(message['Body'])
                    rekMessage = json.loads(notification['Message'])
                    print(rekMessage['JobId'])
                    print(rekMessage['Status'])
                    if str(rekMessage['JobId']) == response['JobId']:
                        print('Matching Job Found:' + rekMessage['JobId'])
                        jobFound = True
                        #=============================================
                        self.GetResultsFaceSearchCollection(rekMessage['JobId'])
                        #=============================================

                        sqs.delete_message(QueueUrl=self.queueUrl,
                                       ReceiptHandle=message['ReceiptHandle'])
                    else:
                        print("Job didn't match:" +
                              str(rekMessage['JobId']) + ' : ' + str(response['JobId']))
                    # Delete the unknown message. Consider sending to dead letter queue
                    sqs.delete_message(QueueUrl=self.queueUrl,
                                   ReceiptHandle=message['ReceiptHandle'])

        print('done')

    def GetResultsFaceSearchCollection(self, jobId):
        maxResults = 10
        paginationToken = ''

        finished = False
        results=list()
        while finished == False:
            response = self.rek.get_face_search(JobId=jobId,
                                        MaxResults=maxResults,
                                        NextToken=paginationToken)

            for personMatch in response['Persons']:
                if ('Person' in personMatch):
                    if 'Face' in personMatch['Person']:
                        results.append({"TS": personMatch['Timestamp'],"boundingBox":personMatch['Person']['Face']['BoundingBox'],"personInfo":personMatch['Person']})

                if ('FaceMatches' in personMatch):
                    for faceMatch in personMatch['FaceMatches']:
                        results.append({"TS": personMatch['Timestamp'],"boundingBox":faceMatch['Face']["BoundingBox"],"faceInfo":faceMatch['Face']})
                        
            
            if 'NextToken' in response:
                paginationToken = response['NextToken']
            else:
                finished = True
        
        print json.dumps(results, sort_keys=True)  
             
    def GetResultsLabels(self, jobId):
        maxResults = 10
        paginationToken = ''
        finished = False

        while finished == False:
            response = self.rek.get_label_detection(JobId=jobId,
                                            MaxResults=maxResults,
                                            NextToken=paginationToken,
                                            SortBy='TIMESTAMP')

            print(response['VideoMetadata']['Codec'])
            print(str(response['VideoMetadata']['DurationMillis']))
            print(response['VideoMetadata']['Format'])
            print(response['VideoMetadata']['FrameRate'])

            for labelDetection in response['Labels']:
                print(labelDetection['Label']['Name'])
                print(labelDetection['Label']['Confidence'])
                print(str(labelDetection['Timestamp']))

            if 'NextToken' in response:
                paginationToken = response['NextToken']
            else:
                finished = True





if __name__ == "__main__":

    analyzer=VideoDetect()
    analyzer.main()