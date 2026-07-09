'''
Created on Sep 6, 2011

@author: Phillipe Wernette, PhD
Director, Remote Sensing & GIS Research and Outreach Services (RS&GIS)
Michigan State University, East Lansing, MI 48823
pwernett@msu.edu

MORE INFORMATION ABOUT CASTING TRANSECTS VIA SCRIPTING:
http://forums.arcgis.com/threads/49206-Perpendicular-transects-at-regular-intervals?p=169011#post169011
'''
import arcpy
import time
from arcpy import env
env.overwriteOutput = True

def create_out_table(outpath, loc):
    arcpy.CreateFeatureclass_management(path, str(location) + '_transects', "POLYLINE", spatial_reference = outpath + loc + '_shorelines')
    outputfc = outpath + loc + '_transects'
    arcpy.AddField_management(outputfc, "TRANSECT_LOCATION", "TEXT", "#", "#", "20")
    arcpy.AddField_management(outputfc, "TRANSECT_NO", "SHORT")
    arcpy.AddField_management(outputfc, "TRANSECT_ID", "TEXT", "#", "#", "20")

path = ''  # TODO: set path to your ArcGIS geodatabase

locations = ['alcona','allegan','manistee','sanilac']

alcona_years = ['1938','1952','1963','1979','1992','1998','2005','2009','2010']
allegan_years = ['1938','1950','1960','1967','1974','1998','2005','2009','2010']
manistee_years = ['1938','1952','1965','1973','1992','1998','2005','2009','2010']
sanilac_years = ['1941','1955','1963','1982','1998','2005','2009','2010']

for location in locations:
    if location == 'alcona':
        print 'Starting: ' + str(location)
        
        outfc = path + location + '_transects'
        
        if not arcpy.Exists(outfc):
            create_out_table(path, location)
    
        years = alcona_years
        for year in years:
            arcpy.AddField_management(outfc, 'TO_' + str(year), "FLOAT", "10", "10", "20")
            
            
    if location == 'allegan':
        print 'Starting: ' + str(location)
        
        outfc = path + location + '_transects'
        
        if arcpy.Exists(outfc):
            print str(outfc) + ' does not exist. Creating this now...'
            create_out_table(path, location)
    
        years = allegan_years
        for year in years:
            arcpy.AddField_management(outfc, 'TO_' + str(year), "FLOAT", "10", "10", "20")
            
            
    if location == 'manistee':
        print 'Starting: ' + str(location)
        
        outfc = path + location + '_transects'
        
        if arcpy.Exists(outfc):
            print str(outfc) + ' does not exist. Creating this now...'
            create_out_table(path, location)
    
        years = manistee_years
        for year in years:
            arcpy.AddField_management(outfc, 'TO_' + str(year), "FLOAT", "10", "10", "20")
            
            
    if location == 'sanilac':
        print 'Starting: ' + str(location)
        
        outfc = path + location + '_transects'
        
        if arcpy.Exists(outfc):
            print str(outfc) + ' does not exist. Creating this now...'
            create_out_table(path, location)
    
        years = sanilac_years
        for year in years:
            arcpy.AddField_management(outfc, 'TO_' + str(year), "FLOAT", "10", "10", "20")

'''
import arcpy, math, random

#Read parameters
linefc = arcpy.GetParameterAsText(0) #Roads feature class
pointfc = arcpy.GetParameterAsText(1) #Known stream crossings feature class
linefolder = arcpy.GetParameterAsText(2) #Workspace for culverts output
culvertlen = int(arcpy.GetParameterAsText(3))

#Create intermediate and final feature classes
linefc2 = linefolder + "/culverts" #Culverts file path
pointfc2 = "in_memory/temppoints" #Intermediate, artificial crossings
arcpy.CreateFeatureclass_management("in_memory", "temppoints", "POINT", "#", "#", "#", r"Coordinate Systems/Projected Coordinate Systems/Utm/Nad 1983/NAD 1983 UTM Zone 11N.prj")
arcpy.CreateFeatureclass_management(linefolder, "culverts", "POLYLINE", "#", "#", "#", r"Coordinate Systems/Projected Coordinate Systems/Utm/Nad 1983/NAD 1983 UTM Zone 11N.prj")

#Delete any existing features in culverts or artificial crossings
if arcpy.Exists(pointfc2):
    arcpy.DeleteFeatures_management(pointfc2)
if arcpy.Exists(linefc2):
    arcpy.DeleteFeatures_management(linefc2)

#Find all crossings within 10m of a road
arcpy.Near_analysis(pointfc, linefc, "10 Meters")

#Find shape field in stream crossing feature class
desc = arcpy.Describe(pointfc)
pointshapefield = desc.ShapeFieldName

#Create search and insert cursors
rows = arcpy.SearchCursor(pointfc)
insrow = arcpy.InsertCursor(pointfc2)

#Enter for loop to create artificial crossings offset within 1m2 from actual crossing points

for row in rows:
    #Continue if the crossing is <10m from a road
    if row.NEAR_DIST != -1:
        feat = row.getValue(pointshapefield)
        pnt1 = feat.getPart()
        pnt1x = pnt1.X
        pnt1y = pnt1.Y
        #Offset artificial crossing <=1m in X, <=1m in Y
        randomX = random.random()
        if randomX%2==0:
            randomX = randomX * -1
        randomY = random.random()
        if randomY%2==0:
            randomY = randomY * -1
        pnt2x = pnt1.X + randomX
        pnt2y = pnt1.Y + randomY
        #Insert new point into feature class
        feat2 = insrow.newRow()
        pnt2 = arcpy.CreateObject("Point")
        pnt2.X = pnt2x
        pnt2.Y = pnt2y
        feat2.shape = pnt2
        insrow.insertRow(feat2)

del row
del insrow
del rows

#Calculate angle to nearest road
arcpy.Near_analysis(pointfc2, linefc, "11 Meters", "#", "ANGLE")

#Create search and insert cursors
rows2 = arcpy.SearchCursor(pointfc2)
insrow2 = arcpy.InsertCursor(linefc2)

#Find shape field
desc2 = arcpy.Describe(pointfc2)

#Create array to hold new lines
lineArray = arcpy.CreateObject("Array")    

#Enter for loop to create culverts

for row2 in rows2:
    feat = row2.getValue(desc2.ShapeFieldName)
    pnt1 = feat.getPart()
    pnt1rad = math.radians(row2.NEAR_ANGLE)
    #Create point at far end of culvert 
    pnt2 = arcpy.CreateObject("Point")
    pnt2.X = (math.cos(pnt1rad) * ((culvertlen/2) + row2.NEAR_DIST)) + pnt1.X
    pnt2.Y = (math.sin(pnt1rad) * ((culvertlen/2) + row2.NEAR_DIST)) + pnt1.Y
    #Create point at close end of culvert
    pnt3 = arcpy.CreateObject("Point")
    pnt3.X = (-1*(math.cos(pnt1rad) * ((culvertlen/2) - row2.NEAR_DIST))) + pnt1.X
    pnt3.Y = (-1*(math.sin(pnt1rad) * ((culvertlen/2) - row2.NEAR_DIST))) + pnt1.Y
    #Put points in array
    lineArray.add(pnt3)
    lineArray.add(pnt2)
    feat3 = insrow2.newRow()
    #Connect points and insert into feature class
    feat3.shape = lineArray
    insrow2.insertRow(feat3)
    #Erase points from array for next loop
    lineArray.removeAll()
del row2
del insrow2
del rows2
'''