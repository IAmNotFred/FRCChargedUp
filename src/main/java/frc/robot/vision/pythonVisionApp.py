#!/usr/bin/env python3
from cscore import CameraServer
from networktables import NetworkTablesInstance
from networktables import NetworkTables
from apriltag import apriltag

import time
import cv2
import json
import numpy as np
import math
import threading

class CameraView(object):
    def __init__(self, camera, vertFOV, horizFOV, elevationOfTarget, elevationOfCamera, angleFromHoriz):
        self.camera = camera
        self.width = self.camera['width']
        self.height = self.camera['height']
        self.vertFOV = vertFOV
        self.horizFOV = horizFOV
        self.elevationOfTarget = elevationOfTarget
        self.elevationOfCamera = elevationOfCamera
        self.angleFromHoriz = angleFromHoriz
        self.cameraCenter = self.width/2
        self.radiusFromAxisOfRotation = 14/12 # measured in feet

class AprilTagTarget(object):
    def __init__(self, camera, coor, id):
        self.id = id
        self.offset = coor[0] - camera.cameraCenter
        self.normalizedY = (coor[1] - camera.height/2)/(camera.height/2) * -1
        self.normalizedX = (coor[0] - camera.width/2)/(camera.width/2)
        self.pitch = (self.normalizedY/2) * camera.vertFOV
        self.yaw = (self.normalizedX/2) * camera.horizFOV
        #(height of target [feet] - height of camera [feet])/tan(pitch [degrees] + angle of camera [degrees])
        self.distanceToTarget = (camera.elevationOfTarget - camera.elevationOfCamera) / math.tan(math.radians(self.pitch + camera.angleFromHoriz))

    def calculateAdjustedYaw(self, radiusFromAxisOfRotation):
        return self.yaw * (radiusFromAxisOfRotation/(self.distanceToTarget+radiusFromAxisOfRotation))
        

class TapeTarget(object):
    def __init__(self, imageResult, approx, tapeTargetDetected, camera, areaR):
        self.tapeTargetDetected = tapeTargetDetected
        self.imageResult = imageResult
        if self.tapeTargetDetected:
            self.x, self.y, self.w, self.h, = cv2.boundingRect(approx)
        else:
            self.x, self.y, self.w, self.h, = 1, 1, 1, 1 
        self.boundingArea = self.w * self.h
        self.normalizedY = (self.y - camera.height/2)/(camera.height/2) * -1
        self.normalizedX = (self.x - camera.width/2)/(camera.width/2)
        self.pitch = (self.normalizedY/2) * camera.vertFOV
        self.yaw = (self.normalizedX/2) * camera.horizFOV
        self.offset = self.x + self.w/2 - camera.cameraCenter
        self.aspectRatio = self.w/self.h
        self.areaRatio = areaR
        #(height of target [feet] - height of camera [feet])/tan(pitch [degrees] + angle of camera [degrees])
        self.distanceToTarget = (camera.elevationOfTarget - camera.elevationOfCamera) / math.tan(math.radians(self.pitch + camera.angleFromHoriz))

    def ordered_cluster(self, data, max_diff):
        current_group = ()
        for item in data:
            test_group = current_group + (item, )
            test_group_mean = mean(test_group)
            if all((abs(test_group_mean - test_item) < max_diff for test_item in test_group)):
                current_group = test_group
            else:
                yield current_group
                current_group = (item, )
        if current_group:
            yield current_group

    def drawRectangle(self):
        # Draw rectangle on the Image
        cv2.rectangle(self.imageResult, (self.x,self.y),(self.x+self.w,self.y+self.h),(0,255,0),3)

class VisionApplication(object):
    def __init__(self):
        self.TITLE = "apriltag_view"
        self.TAG = "tag16h5"
        self.MIN_MARGIN = 10
        self.FONT = cv2.FONT_HERSHEY_SIMPLEX
        self.RED = 0,0,255
        self.detector = apriltag(self.TAG)

        self.imgResult = None
        self.team = None

        self.tapeTargetDetected = False

        self.distanceFromTarget = 0
        self.vision_nt = None 
        self.processingForAprilTags = False
        self.processingForColor = True
        self.usingComputerIP = False 

        # Initialize configuration
        self.config = self.readConfig()
        self.team = self.config["team"]

        self.imgResult = None
        self.mask = None

        self.cameraInUse = 1

        self.aprilTagTargetID = 1

        self.hueMin = 76
        self.hueMax = 127
        self.satMin = 53
        self.satMax = 212
        self.valMin = 89
        self.valMax = 255
       
        self.myColors = [[self.hueMin,self.satMin,self.valMin,self.hueMax,self.satMax,self.valMax]]

        self.areaRatio = 0 # this is the areaRatio of every contour that is seen by the camera
        self.largestAreaRatio = 0 # this is the areaRatio of the target once it has been isolated
        self.aspectRatio = 0 # this is the aspectRatio of every contour that is seen by the camera (width/height)
        self.largestAspectRatio = 0 # this is the aspectRatio fo the target once it has been isolated

        self.garea = 150
        self.contours = None
        self.targets = []
        self.tapeTargetList = []

        #TODO: Fill out values below if distance calculation is desired
        #Vertical Field of View (Degrees)
        vertFOV = 48.94175846

        #Horizontal Field of View (Degrees)
        horizFOV = 134.3449419

        #Height of the target off the ground (feet)
        elevationOfTarget = 18.25/12

        #Height of the Camera off the ground (feet)
        elevationOfCamera = 11.5/12

        #Angle the camera makes relative to the horizontal (degrees)
        angleFromHoriz = 1
        

        self.camera = CameraView(self.config['cameras'][0], vertFOV, horizFOV, elevationOfTarget, elevationOfCamera, angleFromHoriz)
        self.camera2 = CameraView(self.config['cameras'][1], vertFOV, horizFOV, elevationOfTarget, elevationOfCamera, angleFromHoriz)


        # Initialize Camera Server
        self.initializeCameraServer()

        # Initialize NetworkTables Client
        self.initializeNetworkTables()

    def readConfig(self):
        config = None
        with open('/boot/frc.json') as fp:
            config = json.load(fp)
        return config

    def initializeCameraServer(self):
        cserver = CameraServer.getInstance()
        camera1 = cserver.startAutomaticCapture(name="cam1", path='/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_AE5D327F-video-index0')
        camera1.setResolution(self.camera.width,self.camera.height)

        camera2 = cserver.startAutomaticCapture(name="cam2", path='/dev/v4l/by-id/usb-Ingenic_Semiconductor_CO.__LTD._HD_Web_Camera_Ucamera001-video-index0')
        camera2.setResolution(self.camera2.width,self.camera2.height)

        


        self.cvsrc = cserver.putVideo("visionCam", self.camera.width,self.camera.height)
        self.cvmask = cserver.putVideo("maskCam", self.camera.width, self.camera.height)
        
        self.sink = cserver.getVideo(name="cam1")
        self.sink2 = cserver.getVideo(name="cam2")

    def initializeNetworkTables(self):
        # Table for vision output information
        ntinst = NetworkTablesInstance.getDefault()
        
        cond = threading.Condition()
        notified = [False]

        def connectionListener(connected, info):
            print(info, '; Connected=%s' % connected)
            with cond:
                notified[0] = True
                cond.notify()

        # Decide whether to start using team number or IP address
        if self.usingComputerIP:
            ip = '192.168.102.168' #ip of the computer
            # Ex: ip = '192.168.132.5'
            print("Setting up NetworkTables client for team {} at {}".format(self.team,ip))
            ntinst.startClient(ip)
        else:
            ntinst.startClientTeam(self.team)
            print("Connected to robot")

        ntinst.addConnectionListener(connectionListener, immediateNotify=True)

        with cond:
            print("Waiting")
            if not notified[0]:
                cond.wait()

        print("Connected!")
        
        self.vision_nt = ntinst.getTable('Shuffleboard/Vision')

    def putMaskingValues(self):
        self.vision_nt.putNumber('hueMin',self.hueMin)
        self.vision_nt.putNumber('hueMax',self.hueMax)
        self.vision_nt.putNumber('satMin',self.satMin)
        self.vision_nt.putNumber('satMax',self.satMax)
        self.vision_nt.putNumber('valMin',self.valMin)
        self.vision_nt.putNumber('valMax',self.valMax)

    def getMaskingValues(self):
        self.hueMin = int(self.vision_nt.getNumber('hueMin',self.hueMin))
        self.hueMax = int(self.vision_nt.getNumber('hueMax',self.hueMax))
        self.satMin = int(self.vision_nt.getNumber('satMin',self.satMin))
        self.satMax = int(self.vision_nt.getNumber('satMax',self.satMax))
        self.valMin = int(self.vision_nt.getNumber('valMin',self.valMin))
        self.valMax = int(self.vision_nt.getNumber('valMax',self.valMax))
        self.myColors = [[self.hueMin,self.satMin,self.valMin,self.hueMax,self.satMax,self.valMax]]

    def getAprilTagTargetID(self):
        self.aprilTagTargetID = self.vision_nt.getNumber('aprilTagTargetID',1)

    def getDetectionMode(self):
        detectionMode = self.vision_nt.getNumber('detectionMode',0)
        if detectionMode == 0:
            self.processingForColor = False
            self.processingForAprilTags = False
            self.cameraInUse = 0
        elif detectionMode == 1:
            self.processingForColor = True
            self.processingForAprilTags = False
            self.cameraInUse = 1
        elif detectionMode == 2:
            self.processingForColor = False
            self.processingForAprilTags = True
            self.cameraInUse = 2

    def getImageMask(self, img, myColors):
        imgHSV = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)  
        lower = np.array(myColors[0][0:3])
        upper = np.array(myColors[0][3:6])
        mask = cv2.inRange(imgHSV, lower, upper)
        return mask


    def getContours(self, img):
        tempImg, contours, hierarchy = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        return contours

    def isolateTarget(self, contours):
        aspectTolerance = .23
        idealAreaRatio = 0.6 # this is the ideal ratio for the area ratio value.
        idealAspectRatio = 1.2 # this is the ideal aspect ratio based off of the diagram but can be changed as needed.
        areaTolerance = .2 # this is the tolerance for finding the target with the right aspect ratio
        
        idealYCoor = 100
        yCoorTolerance = 20

        idealXCoor = self.camera.width/2
        xCoorTolerance = 70

        deltaAreaTolerance = 400
        # start off with a large tolerance, and if the ideal ratio is correct, lower the tolerance as needed. 
        self.targets = [] 
        
        self.tapeTargetDetected = False
        if len(contours) > 0:
            largest = contours[0]
            area = 0
            for contour in contours:
                contourArea = cv2.contourArea(contour) #area of the particle
                x, y, w, h, = cv2.boundingRect(contour)
                boundingArea = w * h
                if (boundingArea < 100):
                    continue
                if not ((y < (idealYCoor + yCoorTolerance)) and (y > (idealYCoor - yCoorTolerance))):
                    continue
                if not ((x < (idealXCoor + xCoorTolerance)) and (x > (idealXCoor - xCoorTolerance))):
                    continue
                self.areaRatio = contourArea/boundingArea
                self.aspectRatio = w/h
                if self.areaRatio > idealAreaRatio - areaTolerance and self.areaRatio < idealAreaRatio + areaTolerance: # if the targets is within the right area ratio range, it is possibly the correct target
                    if self.aspectRatio > idealAspectRatio - aspectTolerance and self.aspectRatio < idealAspectRatio + aspectTolerance: # if the target is within the correct aspect ratio range aswell, it is definitely the right target
                        largest = contour
                        self.tapeTargetDetected = True
                        self.garea = boundingArea
                        self.targets.append(contour)
                        # Draw the contours
                        cv2.drawContours(self.imgResult, largest, -1, (255,0,0), 3)

    def drawBoundingBox(self):
        if self.tapeTargetDetected:
            for target in self.targets:
                try:
                    peri = cv2.arcLength(target, True)
                except:
                    print("CV2 Error")
                    continue
                approx = cv2.approxPolyDP(target, 0.02 * peri, True)
                x, y, w, h, = cv2.boundingRect(target)
                boundingArea = w * h
                contourArea = cv2.contourArea(target)
                self.tapeTargetList.append(TapeTarget(self.imgResult, approx, self.tapeTargetDetected, self.camera,(contourArea/boundingArea)))
        else:
            approx = None

    def processImgForTape(self, input_img):
        self.getMaskingValues()
        self.mask = self.getImageMask(input_img,self.myColors)
        self.contours = self.getContours(self.mask)
        self.isolateTarget(self.contours)
        self.drawBoundingBox()

    def runApplication(self):
        input_img1 = np.zeros(shape=(self.camera.height,self.camera.width,3),dtype=np.uint8)
        targetDetTol = 1.0 
        t1 = 0
        t2 = 0
        while True:
            self.getDetectionMode()
            print(self.cameraInUse)
            if self.cameraInUse == 1:
                frame_time1, input_img1 = self.sink.grabFrame(input_img1)
                input_img1 = cv2.resize(input_img1, (self.camera.width,self.camera.height), interpolation = cv2.INTER_AREA)
            else:
                frame_time1, input_img1 = self.sink2.grabFrame(input_img1)
                input_img1 = cv2.resize(input_img1, (self.camera2.width,self.camera2.height), interpolation = cv2.INTER_AREA)
            
            self.imgResult = input_img1.copy()
            # Notify output of error and skip iteration
            if frame_time1 == 0:
                self.cvsrc.notifyError(self.sink.getError())
                print("Error on line 135 with grabbing frame")
                continue
            
            if self.processingForAprilTags:
                self.getAprilTagTargetID()
                try:
                    greys = cv2.cvtColor(input_img1, cv2.COLOR_BGR2GRAY)
                    dets = self.detector.detect(greys)
                except RuntimeError:
                    print("RuntimeError with detector")
                    continue
                aprilTagTargets = dict()
            
                for det in dets:
                    if det["margin"] >= self.MIN_MARGIN:
                        rect = det["lb-rb-rt-lt"].astype(int).reshape((-1,1,2))
                        cv2.polylines(self.imgResult, [rect], True, self.RED, 2)
                        ident = str(det["id"])
                        pos = det["center"].astype(int) + (-10,10)
                        aprilTagTargets.update({det["id"]:AprilTagTarget(self.camera2,pos,det["id"])})
                        cv2.putText(self.imgResult, ident, tuple(pos), self.FONT, 1, self.RED, 2)

                if not aprilTagTargets: 
                    # If no apriltags are detected, targetDetected is set to false
                    self.vision_nt.putNumber('aprilTagTargetDetected',0)
                else:
                    if self.aprilTagTargetID in aprilTagTargets:
                        # If AprilTags are detected, targetDetected is set to true 
                        self.vision_nt.putNumber('aprilTagTargetDetected',1)
                        # Publishes data to Network Tables
                        self.vision_nt.putNumber('offset',aprilTagTargets[self.aprilTagTargetID].offset)
                        self.vision_nt.putNumber('targetX',aprilTagTargets[self.aprilTagTargetID].normalizedX)
                        #self.vision_nt.putNumber('robotYaw',aprilTagTargets[self.aprilTagTargetID].calculateAdjustedYaw(self.camera.radiusFromAxisOfRotation))
                        # If you want to calculate distance, make sure to fill out the appropriate variables starting on line 59
                        #self.vision_nt.putNumber('distanceToTarget',aprilTagTargets[self.aprilTagTargetID].distanceToTarget)
                        NetworkTables.flush()
                    

            if self.processingForColor:
                self.tapeTargetList = []
                self.targets = []
                self.processImgForTape(input_img1)
                # sorts the list of tape targets from left to right
                t2 = time.clock_gettime(time.CLOCK_MONOTONIC) # gets the current "time"
                timeDiff = t2-t1 # difference between the most recent time and the time recorded when the target was last seen
                if self.tapeTargetDetected:
                    self.tapeTargetList.sort(key=lambda target: target.boundingArea)
                    self.vision_nt.putNumber('offset',self.tapeTargetList[len(self.tapeTargetList)-1].offset)
                    self.tapeTargetList[len(self.tapeTargetList)-1].drawRectangle()
                    self.vision_nt.putNumber('ycoor',self.tapeTargetList[len(self.tapeTargetList)-1].y)
                    self.vision_nt.putNumber('areaRatio',self.tapeTargetList[len(self.tapeTargetList)-1].areaRatio)
                    self.vision_nt.putNumber('aspectRatio',self.tapeTargetList[len(self.tapeTargetList)-1].aspectRatio)

                    t1 = t2
                    self.vision_nt.putNumber('tapeTargetDetected',1)
                    self.vision_nt.putNumber('BoundingArea',self.garea)
                
                else: # only sets updates the targetDetected if a certain amount of time has passed
                    if timeDiff > targetDetTol:
                        self.vision_nt.putNumber('tapeTargetDetected',0)
                self.cvmask.putFrame(self.mask)

            self.cvsrc.putFrame(self.imgResult)

def main():
    visionApp = VisionApplication()
    visionApp.runApplication()

main()   
