'''
Created on Jun 14, 2012

Copyright 2012: Phil Wernette

This script is designed to convert all vector buffers to rasters and then compile the rasters into a single layer
that displays where the shoreline has changed the most
NOTES:
    1: Shorelines for all four sites must be stored in the same geodatabase
    2: Shoreline feature classes must follow the naming convention:
        name = (location)_shoreline_(year)    example: 'alcona_shoreline_1938'
    3: Before running script be sure that the locations array is accurate.
'''
T = True
F = False

import time
import arcpy
from arcpy.sa import *
from arcpy import env
env.overwriteOutput = T

# Paths where data is stored and saved throughout processing
path = 'C:/Users/Phil/Documents/ArcGIS/Default.gdb/' # Geodatabase pathname
gdb = 'C:/Users/Phil/Documents/ArcGIS/Epsilon_analysis_NONoverlap.gdb/'

# List of the four location to be assessed
locations = ['alcona','allegan','manistee','sanilac']

# Corresponding list of years to be analyzed for each site
start_year = 1938
end_year = 2010
inc = 1
years_a = range(start_year,end_year + 1,inc)
years_b = range(start_year + 1,end_year + 1,inc)

# List of files to delete at the conclusion of the script
clean_list = []

start_time = time.time() #Start the timer for the overall processing

for l in locations:
    # Generate empty array that will be populated with feature classes later in the script
    list = []
    
    # Loop through all the years for any given site
    for a in years_a:
        # Define name of shoreline A
        line_a = gdb + l + '_shoreline_buffer_' + str(a)
        
        # Appends the empty list object with the relevant feature classes
        if arcpy.Exists(line_a):
            list.append(line_a)
    
    outfile = gdb + l + '_shoreline_sim_geoprocess'
    
    # If the output file already exists, then it is deleted and regenerated with the new data
    if arcpy.Exists(outfile):
        arcpy.Delete_management(outfile)
    arcpy.Union_analysis(list, outfile, 'ONLY_FID')
    
    # Add a new field to the feature class to represent the number of overlapping shorelines
    # This new field is also known as the 'Similarity Index'
    new_att = 'Similarity_Index'
    arcpy.AddField_management(outfile, new_att, 'SHORT')
    
    # Generate List of attributes
    fieldnames = [f.name for f in arcpy.ListFields(outfile)]
    
    # Replace -1's with 0's AND sum the attributes to populate the Similarity Index attribute
    rows = arcpy.UpdateCursor(outfile)
    for row in rows:
        val = 0
        for name in fieldnames:
            if name != new_att:
                if row.getValue(name) == -1:
                    row.setValue(name, 0)
                elif name != 'OBJECTID' and row.getValue(name) == 1:
                    val = val + 1
            elif name == new_att:
                row.setValue(name, val)
            rows.updateRow(row)
    del rows

elapsed_time = time.time() - start_time

if elapsed_time < 60:
    print "Elapsed time: " + str(elapsed_time) + ' seconds'
elif elapsed_time >= 60 and elapsed_time < 3600:
    print "Elapsed time: " + str(elapsed_time/60) + ' minutes'
elif elapsed_time >= 3600:
    print "Elapsed time: " + str(elapsed_time/3600) + ' hours'