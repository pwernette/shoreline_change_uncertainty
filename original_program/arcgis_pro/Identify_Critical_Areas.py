'''
Created on 15 December 2011

@author: Phil Wernette

Updated: 17 January 2012; 02 February 2012; 05 February 2012, 17 March 2012, 23 March 2012

This script is designed to do a comprehensive epsilon bands analysis for each research site. It loops through all of the specified
locations and years at each of the specified confidence levels. Each year's shoreline at a given site is analyzed from and to all other
shorelines at the same site. The results of these analyses are output into the same geodatabase as the shorelines themselves.

CFOR MORE INFORMATION ABOUT MEASURING THE DISTANCE BETWEEN TWO LINEAR FEATURES:
http://forums.arcgis.com/threads/47780-Distance-between-two-linear-features

NOTES:
    1: Shorelines for all four sites must be stored in the same geodatabase
    2: Shoreline feature classes must follow the naming convention:
        name = (location)_shoreline_(year)    example: 'alcona_shoreline_1938'
    3: Before running script be sure that the locations and years arrays are complete and consistent with the feature classes present.

UPDATE (23 March 2012): The option to export the intersected shoreline segments has been added as a method of identifying areas of
shoreline that are experiencing significant changes.
'''

import time
import arcpy
from arcpy import env
env.overwriteOutput = True

def create_out_table(outpath, loc, thresh):
    outtbl = path + loc + 'ShorelineBufferTable' + str(percent_threshold)
    arcpy.CreateTable_management(outpath, str(loc) + 'ShorelineBufferTable' + str(thresh))
    arcpy.AddField_management(outtbl, "ID", "TEXT", "#", "#", "20")
    arcpy.AddField_management(outtbl, "FROM_YEAR", "SHORT")
    arcpy.AddField_management(outtbl, "TO_YEAR", "SHORT")
    arcpy.AddField_management(outtbl, "MIN_DIST", "FLOAT", "10","10","20")
    arcpy.AddField_management(outtbl, "MEAN_DIST", "FLOAT", "10","10","20")
    arcpy.AddField_management(outtbl, "MAX_DIST", "FLOAT", "10","10","20")
    arcpy.AddField_management(outtbl, "THRESHOLD", "FLOAT", "10", "10", "20")
    arcpy.AddField_management(outtbl, "BUFFER_RADIUS", "TEXT", "#", "#", "20")
    arcpy.AddField_management(outtbl, "OBS_LENGTH", "FLOAT", "10", "10", "20")
    del outpath, loc, thresh, outtbl
    
def insert_out_row(insert_cursor):
    row = insert_cursor.newRow()
    row.ID = str(year) + '_' + str(k)
    row.FROM_YEAR = year
    row.TO_YEAR = k
    row.BUFFER_RADIUS = bufdist
    row.THRESHOLD = threshold
    row.OBS_LENGTH = obs_length
    row.MIN_DIST = mindist
    row.MEAN_DIST = meandist
    row.MAX_DIST = maxdist
    insert_cursor.insertRow(row)
    del row
    
def elapsed_time_out(loc, loc_elapsed):
    if loc_elapsed < 60:
        print 'Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed) + ' seconds'
        if export_table:
            f.write('Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed) + ' seconds\n')
    elif loc_elapsed >= 60 and loc_elapsed < 3600:
        print 'Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed/60) + ' minutes'
        if export_table:
            f.write('Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed) + ' seconds\n')
    elif loc_elapsed >= 3600:
        print 'Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed/3600) + ' hours'
        if export_table:
            f.write('Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed/3600) + ' hours\n')
    del loc, loc_elapsed
    
def clean_up():
    if arcpy.Exists(tempshoreline):
        arcpy.Delete_management(tempshoreline)
    if arcpy.Exists(tempvert):
        arcpy.Delete_management(tempvert)
    if arcpy.Exists(temptable):
        arcpy.Delete_management(temptable)
    if arcpy.Exists(shorelinebuffer):
        arcpy.Delete_management(shorelinebuffer)
        
def copyFC(gdb_path, fc_to_copy, new_name, fc_type):
    newshore = gdb_path + new_name
    arcpy.CreateFeatureclass_management(gdb_path, new_name, fc_type, spatial_reference=fc_to_copy)
    arcpy.CopyFeatures_management(fc_to_copy, newshore)
    del gdb_path, fc_to_copy, new_name, fc_type, newshore

path = 'C:/Users/Phil/Documents/ArcGIS/Default.gdb/' # Geodatabase pathname
outlog_path = 'C:/Users/Phil/Documents/Geography MS/analysis/' # Output log file location

shorelinebuffer = path + 'shorelinebuffer'
tempshoreline = path + 'tempshoreline'
tempvert = path + 'tempshorelineverticies'
temptable = path + 'temptable'

# List of confidence levels to loop the analysis through
#confidence_levels = [0.05,0.10,0.20,0.50,0.90,0.95]
confidence_levels = [0.05]

# List of the four location to be assessed
locations = ['alcona','allegan','manistee','sanilac']

# Corresponding list of years to be analyzed for each site
alcona_years = [1938,1952,1963,1979,1992,1998,2005,2009,2010]
allegan_years = [1938,1950,1960,1967,1974,1998,2005,2009,2010]
manistee_years = [1938,1952,1965,1973,1992,1998,2005,2009,2010]
sanilac_years = [1941,1955,1963,1982,1998,2005,2009,2010]

# Set which locations should be analyzed:
alcona_skip = False
allegan_skip = False
manistee_skip = False
sanilac_skip = False

# Esporting options
export_table = False #Results are exported if this is set to TRUE
export_intersected_segments = True #Intersected shoreline segments are exported if this is set to TRUE

start_time = time.time() 

for confidence_level in confidence_levels:
    # This is the the adjacent shoreline used to create the threshold
    #confidence_level = 0.05 # Amount in PROPORTION
    percent_threshold = str(confidence_level).split('.')[1]  #Amount in PERCENT
    
    #start_time = time.time() #Record how long it takes
    
    for location in locations:
        '''
        ######################## ALCONA COUNTY ########################
        '''
        if location == 'alcona':
            if not alcona_skip:
                location_start = time.time() # Start timer
                
                if export_table:
                    out_table = path + location + 'ShorelineBufferTable' + str(percent_threshold)
                    
                    f = open(outlog_path + str(location) + '_output_log' + str(percent_threshold) + '.txt','w')
                    f.write('Site: ' + str(location) + '\n')
                    f.write('Confidence Level: ' + str(confidence_level) + '\n')
                    
                    log = open(outlog_path + str(location) + '_epsilon_bands_results' + str(percent_threshold) + '.txt','w')
                    log.write('Site: ' + str(location) + '\n')
                    log.write('Confidence Level: ' + str(confidence_level) + '\n')
                    log.write('site | from_year | to_year | buffer_radius | threshold | observed_length | min_dist | mean_dist | max_dist\n')
                
                    #Check to see if the output table already exists (delete it, if it does)
                    if arcpy.Exists(out_table):
                        arcpy.Delete_management(out_table)
                    create_out_table(path, location, percent_threshold)
                
                    # Create search cursor to insert new data into the table
                    cur = arcpy.InsertCursor(out_table)
                    
                # List of years in site to analyze from
                years = alcona_years
                
                # Loop through all the years for any given site
                for year in years:
                    inshore = path + location + '_shoreline_' + str(year)
                    
                    if arcpy.Exists(inshore):
                        # Convert shoreline verticies to points to calculate minimum and mean distances
                        arcpy.FeatureVerticesToPoints_management(inshore, tempvert, "ALL")
                            
                        # List of years in site to analyze to
                        testagainstyears = alcona_years
                        for k in testagainstyears:
                            if k > year:
                                print 'Beginning ' + str(year) + ' -to- ' + str(k)
                                if export_table:
                                    f.write('Beginning ' + str(year) + ' -to- ' + str(k) + '\n')
                                
                                adjacentshore = path + location + '_shoreline_' + str(k)
                                
                                if arcpy.Exists(adjacentshore):
                                    # Perform NEAR analysis on verticies of base shoreline and determine the min and mean distances
                                    arcpy.Near_analysis(tempvert,adjacentshore,"1000 Meters","NO_LOCATION","NO_ANGLE")
                                    arcpy.Statistics_analysis(tempvert,temptable,"NEAR_DIST MIN;NEAR_DIST MEAN;NEAR_DIST MAX","#")
                                    
                                    # Search cursors used to define minimum and mean distance values
                                    searchrows = arcpy.SearchCursor(temptable, "", "", "MIN_NEAR_DIST; MEAN_NEAR_DIST; MAX_NEAR_DIST")
                                    for r in searchrows:
                                        mindist = r.MIN_NEAR_DIST
                                        meandist = r.MEAN_NEAR_DIST
                                        maxdist = r.MAX_NEAR_DIST
                                        
                                    # Get minimum threshold for 
                                    t = arcpy.Geometry()
                                    tgeometryList = arcpy.CopyFeatures_management(adjacentshore, t)
                                    tlength = 0 #Sets default length to 0 before calculating observed length
                                    for tgeometry in tgeometryList:
                                        tlength += tgeometry.length
                                    threshold = (confidence_level * tlength) # Calculates threshold for length of adjacent shoreline to be included
                                    #print str(inshore) + " threshold= " + str(threshold)
                                            
                                    obs_length = 0
                                    
                                    if mindist <> 0:
                                        bufdist = mindist
                                    else:
                                        bufdist = 0.5
                                    
                                    while obs_length < threshold:
                                        arcpy.Buffer_analysis(inshore, shorelinebuffer, str(bufdist) + ' METERS', 'FULL', 'ROUND', 'ALL')
                                        arcpy.Intersect_analysis([adjacentshore, shorelinebuffer], tempshoreline, 'ALL', output_type='LINE')
                                        
                                        # Get length of observed temporary shoreline
                                        g = arcpy.Geometry()
                                        geometryList = arcpy.CopyFeatures_management(tempshoreline, g)
                                        length = 0
                                        for geometry in geometryList:
                                            length += geometry.length
                                        obs_length = length
                                        
                                        if obs_length < threshold:
                                            print str((obs_length/threshold)*100) + '% at ' + str(bufdist)
                                            
                                            if export_table:
                                                f.write(str(((obs_length/threshold)*100)) + '% at ' + str(bufdist) + '\n')
                                            
                                            bufdist = bufdist + 0.5
                                            #print "New buffer distance: " + str(bufdist) + " METERS"
                                        
                                    if export_intersected_segments:
                                        copyFC(path, tempshoreline, str(location) + str(year) + '_' + str(k) + '_' + str(percent_threshold) + '_intersect', "POLYLINE")
     
                                    if export_table:
                                        # Output results to log file
                                        log.write(str(location) + '|' + str(year) + '|' + str(k) + '|' + str(bufdist) + '|' + str(threshold) + '|' + str(obs_length) + '|' + str(mindist) + '|' + str(meandist) + '|' + str(maxdist) + '\n')
                                        
                                        # Insert row with key statistics
                                        insert_out_row(cur)
                                    
                                        f.write('\n')
                if export_table:
                    del cur, r
                
                # Calculate elapsed time for the given location
                location_elapsed = time.time() - location_start
                
                # Print and Export Elapsed Time
                elapsed_time_out(location, location_elapsed)
                
                if export_table:
                    # Close oujtput log files
                    f.close()
                    log.close()
                
                # Clean up temp files
                clean_up()
        
        '''
        ######################## ALLEGAN COUNTY ########################
        '''    
        if location == 'allegan':
            if not allegan_skip:
                location_start = time.time() # Start timer
                
                location_start = time.time() # Start timer
                
                if export_table == 'True':
                    out_table = path + location + 'ShorelineBufferTable' + str(percent_threshold)
                    
                    f = open(outlog_path + str(location) + '_output_log' + str(percent_threshold) + '.txt','w')
                    f.write('Site: ' + str(location) + '\n')
                    f.write('Confidence Level: ' + str(confidence_level) + '\n')
                    
                    log = open(outlog_path + str(location) + '_epsilon_bands_results' + str(percent_threshold) + '.txt','w')
                    log.write('Site: ' + str(location) + '\n')
                    log.write('Confidence Level: ' + str(confidence_level) + '\n')
                    log.write('site | from_year | to_year | buffer_radius | threshold | observed_length | min_dist | mean_dist | max_dist\n')
                
                    #Check to see if the output table already exists (delete it, if it does)
                    if arcpy.Exists(out_table):
                        arcpy.Delete_management(out_table)
                    create_out_table(path, location, percent_threshold)
                
                    # Create search cursor to insert new data into the table
                    cur = arcpy.InsertCursor(out_table)
                    
                # List of years in site to analyze from
                years = allegan_years
                
                # Loop through all the years for any given site
                for year in years:
                    inshore = path + location + '_shoreline_' + str(year)
                    
                    if arcpy.Exists(inshore):
                        # Convert shoreline verticies to points to calculate minimum and mean distances
                        arcpy.FeatureVerticesToPoints_management(inshore, tempvert, "ALL")
                            
                        # List of years in site to analyze to
                        testagainstyears = allegan_years
                        for k in testagainstyears:
                            if k > year:
                                print 'Beginning ' + str(year) + ' -to- ' + str(k)
                                if export_table:
                                    f.write('Beginning ' + str(year) + ' -to- ' + str(k) + '\n')
                                
                                adjacentshore = path + location + '_shoreline_' + str(k)
                                
                                if arcpy.Exists(adjacentshore):
                                    # Perform NEAR analysis on verticies of base shoreline and determine the min and mean distances
                                    arcpy.Near_analysis(tempvert,adjacentshore,"1000 Meters","NO_LOCATION","NO_ANGLE")
                                    arcpy.Statistics_analysis(tempvert,temptable,"NEAR_DIST MIN;NEAR_DIST MEAN;NEAR_DIST MAX","#")
                                    
                                    # Search cursors used to define minimum and mean distance values
                                    searchrows = arcpy.SearchCursor(temptable, "", "", "MIN_NEAR_DIST; MEAN_NEAR_DIST; MAX_NEAR_DIST")
                                    for r in searchrows:
                                        mindist = r.MIN_NEAR_DIST
                                        meandist = r.MEAN_NEAR_DIST
                                        maxdist = r.MAX_NEAR_DIST
                                        
                                    # Get minimum threshold for 
                                    t = arcpy.Geometry()
                                    tgeometryList = arcpy.CopyFeatures_management(adjacentshore, t)
                                    tlength = 0 #Sets default length to 0 before calculating observed length
                                    for tgeometry in tgeometryList:
                                        tlength += tgeometry.length
                                    threshold = (confidence_level * tlength) # Calculates threshold for length of adjacent shoreline to be included
                                    #print str(inshore) + " threshold= " + str(threshold)
                                            
                                    obs_length = 0
                                    
                                    if mindist <> 0:
                                        bufdist = mindist
                                    else:
                                        bufdist = 0.5
                                    
                                    while obs_length < threshold:
                                        arcpy.Buffer_analysis(inshore, shorelinebuffer, str(bufdist) + ' METERS', 'FULL', 'ROUND', 'ALL')
                                        arcpy.Intersect_analysis([adjacentshore, shorelinebuffer], tempshoreline, 'ALL', output_type='LINE')
                                        
                                        # Get length of observed temporary shoreline
                                        g = arcpy.Geometry()
                                        geometryList = arcpy.CopyFeatures_management(tempshoreline, g)
                                        length = 0
                                        for geometry in geometryList:
                                            length += geometry.length
                                        obs_length = length
                                        
                                        if obs_length < threshold:
                                            print str((obs_length/threshold)*100) + '% at ' + str(bufdist)
                                            
                                            if export_table:
                                                f.write(str(((obs_length/threshold)*100)) + '% at ' + str(bufdist) + '\n')
                                            
                                            bufdist = bufdist + 0.5
                                            #print "New buffer distance: " + str(bufdist) + " METERS"
                                        
                                    if export_intersected_segments:
                                        copyFC(path, tempshoreline, str(location) + str(year) + '_' + str(k) + '_' + str(percent_threshold) + '_intersect', "POLYLINE")
     
                                    if export_table:
                                        # Output results to log file
                                        log.write(str(location) + '|' + str(year) + '|' + str(k) + '|' + str(bufdist) + '|' + str(threshold) + '|' + str(obs_length) + '|' + str(mindist) + '|' + str(meandist) + '|' + str(maxdist) + '\n')
                                        
                                        # Insert row with key statistics
                                        insert_out_row(cur)
                                    
                                        f.write('\n')
                if export_table:
                    del cur, r
                
                # Calculate elapsed time for the given location
                location_elapsed = time.time() - location_start
                
                # Print and Export Elapsed Time
                elapsed_time_out(location, location_elapsed)
                
                if export_table:
                    # Close oujtput log files
                    f.close()
                    log.close()
                
                # Clean up temp files
                clean_up()
                
        '''
        ######################## MANISTEE COUNTY ########################
        '''
        if location == 'manistee':
            if not manistee_skip:
                location_start = time.time() # Start timer
                
                location_start = time.time() # Start timer
                
                if export_table == 'True':
                    out_table = path + location + 'ShorelineBufferTable' + str(percent_threshold)
                    
                    f = open(outlog_path + str(location) + '_output_log' + str(percent_threshold) + '.txt','w')
                    f.write('Site: ' + str(location) + '\n')
                    f.write('Confidence Level: ' + str(confidence_level) + '\n')
                    
                    log = open(outlog_path + str(location) + '_epsilon_bands_results' + str(percent_threshold) + '.txt','w')
                    log.write('Site: ' + str(location) + '\n')
                    log.write('Confidence Level: ' + str(confidence_level) + '\n')
                    log.write('site | from_year | to_year | buffer_radius | threshold | observed_length | min_dist | mean_dist | max_dist\n')
                
                    #Check to see if the output table already exists (delete it, if it does)
                    if arcpy.Exists(out_table):
                        arcpy.Delete_management(out_table)
                    create_out_table(path, location, percent_threshold)
                
                    # Create search cursor to insert new data into the table
                    cur = arcpy.InsertCursor(out_table)
                    
                # List of years in site to analyze from
                years = manistee_years
                
                # Loop through all the years for any given site
                for year in years:
                    inshore = path + location + '_shoreline_' + str(year)
                    
                    if arcpy.Exists(inshore):
                        # Convert shoreline verticies to points to calculate minimum and mean distances
                        arcpy.FeatureVerticesToPoints_management(inshore, tempvert, "ALL")
                            
                        # List of years in site to analyze to
                        testagainstyears = manistee_years
                        for k in testagainstyears:
                            if k > year:
                                print 'Beginning ' + str(year) + ' -to- ' + str(k)
                                if export_table:
                                    f.write('Beginning ' + str(year) + ' -to- ' + str(k) + '\n')
                                
                                adjacentshore = path + location + '_shoreline_' + str(k)
                                
                                if arcpy.Exists(adjacentshore):
                                    # Perform NEAR analysis on verticies of base shoreline and determine the min and mean distances
                                    arcpy.Near_analysis(tempvert,adjacentshore,"1000 Meters","NO_LOCATION","NO_ANGLE")
                                    arcpy.Statistics_analysis(tempvert,temptable,"NEAR_DIST MIN;NEAR_DIST MEAN;NEAR_DIST MAX","#")
                                    
                                    # Search cursors used to define minimum and mean distance values
                                    searchrows = arcpy.SearchCursor(temptable, "", "", "MIN_NEAR_DIST; MEAN_NEAR_DIST; MAX_NEAR_DIST")
                                    for r in searchrows:
                                        mindist = r.MIN_NEAR_DIST
                                        meandist = r.MEAN_NEAR_DIST
                                        maxdist = r.MAX_NEAR_DIST
                                        
                                    # Get minimum threshold for 
                                    t = arcpy.Geometry()
                                    tgeometryList = arcpy.CopyFeatures_management(adjacentshore, t)
                                    tlength = 0 #Sets default length to 0 before calculating observed length
                                    for tgeometry in tgeometryList:
                                        tlength += tgeometry.length
                                    threshold = (confidence_level * tlength) # Calculates threshold for length of adjacent shoreline to be included
                                    #print str(inshore) + " threshold= " + str(threshold)
                                            
                                    obs_length = 0
                                    
                                    if mindist <> 0:
                                        bufdist = mindist
                                    else:
                                        bufdist = 0.5
                                    
                                    while obs_length < threshold:
                                        arcpy.Buffer_analysis(inshore, shorelinebuffer, str(bufdist) + ' METERS', 'FULL', 'ROUND', 'ALL')
                                        arcpy.Intersect_analysis([adjacentshore, shorelinebuffer], tempshoreline, 'ALL', output_type='LINE')
                                        
                                        # Get length of observed temporary shoreline
                                        g = arcpy.Geometry()
                                        geometryList = arcpy.CopyFeatures_management(tempshoreline, g)
                                        length = 0
                                        for geometry in geometryList:
                                            length += geometry.length
                                        obs_length = length
                                        
                                        if obs_length < threshold:
                                            print str((obs_length/threshold)*100) + '% at ' + str(bufdist)
                                            
                                            if export_table:
                                                f.write(str(((obs_length/threshold)*100)) + '% at ' + str(bufdist) + '\n')
                                            
                                            bufdist = bufdist + 0.5
                                            #print "New buffer distance: " + str(bufdist) + " METERS"
                                        
                                    if export_intersected_segments:
                                        copyFC(path, tempshoreline, str(location) + str(year) + '_' + str(k) + '_' + str(percent_threshold) + '_intersect', "POLYLINE")
     
                                    if export_table:
                                        # Output results to log file
                                        log.write(str(location) + '|' + str(year) + '|' + str(k) + '|' + str(bufdist) + '|' + str(threshold) + '|' + str(obs_length) + '|' + str(mindist) + '|' + str(meandist) + '|' + str(maxdist) + '\n')
                                        
                                        # Insert row with key statistics
                                        insert_out_row(cur)
                                    
                                        f.write('\n')
                if export_table:
                    del cur, r
                
                # Calculate elapsed time for the given location
                location_elapsed = time.time() - location_start
                
                # Print and Export Elapsed Time
                elapsed_time_out(location, location_elapsed)
                
                if export_table:
                    # Close oujtput log files
                    f.close()
                    log.close()
                
                # Clean up temp files
                clean_up()
                
        '''
        ######################## SANILAC COUNTY ########################
        '''
        if location == 'sanilac':
            if not sanilac_skip:
                location_start = time.time() # Start timer
                
                location_start = time.time() # Start timer
                
                if export_table == 'True':
                    out_table = path + location + 'ShorelineBufferTable' + str(percent_threshold)
                    
                    f = open(outlog_path + str(location) + '_output_log' + str(percent_threshold) + '.txt','w')
                    f.write('Site: ' + str(location) + '\n')
                    f.write('Confidence Level: ' + str(confidence_level) + '\n')
                    
                    log = open(outlog_path + str(location) + '_epsilon_bands_results' + str(percent_threshold) + '.txt','w')
                    log.write('Site: ' + str(location) + '\n')
                    log.write('Confidence Level: ' + str(confidence_level) + '\n')
                    log.write('site | from_year | to_year | buffer_radius | threshold | observed_length | min_dist | mean_dist | max_dist\n')
                
                    #Check to see if the output table already exists (delete it, if it does)
                    if arcpy.Exists(out_table):
                        arcpy.Delete_management(out_table)
                    create_out_table(path, location, percent_threshold)
                
                    # Create search cursor to insert new data into the table
                    cur = arcpy.InsertCursor(out_table)
                    
                # List of years in site to analyze from
                years = sanilac_years
                
                # Loop through all the years for any given site
                for year in years:
                    inshore = path + location + '_shoreline_' + str(year)
                    
                    if arcpy.Exists(inshore):
                        # Convert shoreline verticies to points to calculate minimum and mean distances
                        arcpy.FeatureVerticesToPoints_management(inshore, tempvert, "ALL")
                            
                        # List of years in site to analyze to
                        testagainstyears = sanilac_years
                        for k in testagainstyears:
                            if k > year:
                                print 'Beginning ' + str(year) + ' -to- ' + str(k)
                                if export_table:
                                    f.write('Beginning ' + str(year) + ' -to- ' + str(k) + '\n')
                                
                                adjacentshore = path + location + '_shoreline_' + str(k)
                                
                                if arcpy.Exists(adjacentshore):
                                    # Perform NEAR analysis on verticies of base shoreline and determine the min and mean distances
                                    arcpy.Near_analysis(tempvert,adjacentshore,"1000 Meters","NO_LOCATION","NO_ANGLE")
                                    arcpy.Statistics_analysis(tempvert,temptable,"NEAR_DIST MIN;NEAR_DIST MEAN;NEAR_DIST MAX","#")
                                    
                                    # Search cursors used to define minimum and mean distance values
                                    searchrows = arcpy.SearchCursor(temptable, "", "", "MIN_NEAR_DIST; MEAN_NEAR_DIST; MAX_NEAR_DIST")
                                    for r in searchrows:
                                        mindist = r.MIN_NEAR_DIST
                                        meandist = r.MEAN_NEAR_DIST
                                        maxdist = r.MAX_NEAR_DIST
                                        
                                    # Get minimum threshold for 
                                    t = arcpy.Geometry()
                                    tgeometryList = arcpy.CopyFeatures_management(adjacentshore, t)
                                    tlength = 0 #Sets default length to 0 before calculating observed length
                                    for tgeometry in tgeometryList:
                                        tlength += tgeometry.length
                                    threshold = (confidence_level * tlength) # Calculates threshold for length of adjacent shoreline to be included
                                    #print str(inshore) + " threshold= " + str(threshold)
                                            
                                    obs_length = 0
                                    
                                    if mindist <> 0:
                                        bufdist = mindist
                                    else:
                                        bufdist = 0.5
                                    
                                    while obs_length < threshold:
                                        arcpy.Buffer_analysis(inshore, shorelinebuffer, str(bufdist) + ' METERS', 'FULL', 'ROUND', 'ALL')
                                        arcpy.Intersect_analysis([adjacentshore, shorelinebuffer], tempshoreline, 'ALL', output_type='LINE')
                                        
                                        # Get length of observed temporary shoreline
                                        g = arcpy.Geometry()
                                        geometryList = arcpy.CopyFeatures_management(tempshoreline, g)
                                        length = 0
                                        for geometry in geometryList:
                                            length += geometry.length
                                        obs_length = length
                                        
                                        if obs_length < threshold:
                                            print str((obs_length/threshold)*100) + '% at ' + str(bufdist)
                                            
                                            if export_table:
                                                f.write(str(((obs_length/threshold)*100)) + '% at ' + str(bufdist) + '\n')
                                            
                                            bufdist = bufdist + 0.5
                                            #print "New buffer distance: " + str(bufdist) + " METERS"
                                        
                                    if export_intersected_segments:
                                        copyFC(path, tempshoreline, str(location) + str(year) + '_' + str(k) + '_' + str(percent_threshold) + '_intersect', "POLYLINE")
     
                                    if export_table:
                                        # Output results to log file
                                        log.write(str(location) + '|' + str(year) + '|' + str(k) + '|' + str(bufdist) + '|' + str(threshold) + '|' + str(obs_length) + '|' + str(mindist) + '|' + str(meandist) + '|' + str(maxdist) + '\n')
                                        
                                        # Insert row with key statistics
                                        insert_out_row(cur)
                                    
                                        f.write('\n')
                if export_table:
                    del cur, r
                
                # Calculate elapsed time for the given location
                location_elapsed = time.time() - location_start
                
                # Print and Export Elapsed Time
                elapsed_time_out(location, location_elapsed)
                
                if export_table:
                    # Close oujtput log files
                    f.close()
                    log.close()
                
                # Clean up temp files
                clean_up()

elapsed_time = time.time() - start_time

if elapsed_time < 60:
    print "Elapsed time: " + str(elapsed_time) + ' seconds'
elif elapsed_time >= 60 and elapsed_time < 3600:
    print "Elapsed time: " + str(elapsed_time/60) + ' minutes'
elif elapsed_time >= 3600:
    print "Elapsed time: " + str(elapsed_time/3600) + ' hours'