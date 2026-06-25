'''
Created on May 29, 2012

@author: Phil Wernette

This script is designed to add the "UNCERTAINTY" field to each shoreline feature class.
Once the new field is manually populated, this attribute will define the radius of the buffer aroud the shoreline
for the subsequent analysis.
'''
T = True

import arcpy
from arcpy import env
env.overwriteOutput = T 

path = 'C:/Users/Phil/Documents/ArcGIS/Default.gdb/' # Geodatabase pathname

# List of the four location to be assessed
locations = ['alcona','allegan','manistee','sanilac']

# Corresponding list of years to be analyzed for each site
start_year = 1938
end_year = 2010
year_increment = 1
years = range(start_year,end_year + 1,year_increment)

for l in locations:
    for y in years:
        fc = path + str(l) + '_shoreline_' + str(y)
        if arcpy.Exists(fc):
            print fc
            
            arcpy.AddField_management(fc, 'UNCERTAINTY', 'FLOAT')
            print 'done with ' + str(l) + ' ' + str(y)