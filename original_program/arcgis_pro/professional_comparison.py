'''
Created on Jan 26, 2012

@author: Phil

This script is designed to cycle through all the professionally-delineated shorelines and calculate the mean distances between them.
Additionally, this same process is repeated for each site and each year between my personally-delineated shoreline and all of the
professionally-delineated shorelines. The results are then output to an overall summary table in the same geodatabase for each site.

FOR MORE INFORMATION ABOUT MEASURING THE DISTANCE BETWEEN TWO LINEAR FEATURES:
http://forums.arcgis.com/threads/47780-Distance-between-two-linear-features

NOTES:
    1: Shorelines (personally and professionally-delineated) must all be stored in the same geodatabase
    2: Shoreline feature classes must follow the naming convention:
        name = (location)_shoreline_(year)    example: 'alcona_shoreline_1938'
    3: Professionally-delineated shorelines must also follow the naming convention:
        name = (location)_shoreline_(year)_(professional)    example: 'alcona_shoreline_1938_acmoody'
'''

import time
import arcpy
from arcpy import env
env.overwriteOutput = True

def create_out_table(outpath, loc, name):
    outtbl = path + str(loc) + str(name)
    arcpy.CreateTable_management(path, str(loc) + str(name))
    arcpy.AddField_management(out_table, "ID", "TEXT", "#", "#", "35")
    arcpy.AddField_management(out_table, "YEAR", "SHORT")
    arcpy.AddField_management(out_table, "FROM", "TEXT", "#", "#", "20")
    arcpy.AddField_management(out_table, "TO_PROF", "TEXT", "#", "#", "20")
    arcpy.AddField_management(out_table, "MIN_DIST", "FLOAT", "10","10","20")
    arcpy.AddField_management(out_table, "MEAN_DIST", "FLOAT", "10","10","20")
    arcpy.AddField_management(out_table, "MAX_DIST", "FLOAT", "10","10","20")
    del outpath, loc, outtbl, name

# Defines the function to insert the appropriate values in the output table
def insert_out_row(insert_cursor, from_string, to_string):
    row = insert_cursor.newRow()
    row.ID = 'TO' + str(professional)
    row.YEAR = year
    row.FROM = from_string
    row.TO_PROF = to_string
    row.MIN_DIST = mindist
    row.MEAN_DIST = meandist
    row.MAX_DIST = maxdist
    insert_cursor.insertRow(row)
    del row

# Cleans up all temp feature classes that were generated
def clean_up():
    if arcpy.Exists(tempshoreline):
        arcpy.Delete_management(tempshoreline)
    if arcpy.Exists(tempvert):
        arcpy.Delete_management(tempvert)
    if arcpy.Exists(temptable):
        arcpy.Delete_management(temptable)
    if arcpy.Exists(tmp):
        arcpy.Delete_management(tmp)

path = 'C:/Users/Phil/Documents/ArcGIS/Default.gdb/'
shorelinebuffer = path + 'shorelinebuffer'
tempshoreline = path + 'tempshoreline'
tempvert = path + 'tempshorelineverticies'
temptable = path + 'temptable'
tmp = path + 'tempsumtable'

# List of the professionally-delineated shorelines to be assessed
professionals = ['acmoody','goodwin','lusch']

# List of locations to be assessed
locations = ['alcona']

# List of the shoreline years to be assessed
years = [1938,1963,1979]

start_time = time.time() #Record how long it takes



'''
# Cycle through and compare my shoreline delineations to each of the three professionally-delineated shorelines
'''
for location in locations:
    metoprof_tbl = path + str(location) + '_meTOprof' 
    
    # Check and possibly create output .dbf table
    if arcpy.Exists(metoprof_tbl):
        arcpy.Delete_management(metoprof_tbl)
    create_out_table(path, location, '_meTOprof')

    for year in years:
        inshore = path + str(location) + '_shoreline_' + str(year)
        
        if arcpy.Exists(inshore):
            # Convert shoreline verticies to points to calculate minimum and mean distances
            arcpy.FeatureVerticesToPoints_management(inshore, tempvert, "ALL")
                
            for professional in professionals:
                print 'ME -- to -- ' + str(professional) + ' ' + str(year)
                adjacentshore = path + str(location) + '_shoreline_' + str(year) + '_' + professional
                
                # Perform NEAR analysis on verticies of base shoreline and determine the min and mean distances
                arcpy.Near_analysis(tempvert,adjacentshore,"1000 Meters","NO_LOCATION","NO_ANGLE")
                arcpy.Statistics_analysis(tempvert,temptable,"NEAR_DIST MIN;NEAR_DIST MEAN;NEAR_DIST MAX","#")
                            
                # Search cursors used to define minimum and mean distance values
                metoprof_searchrows = arcpy.SearchCursor(temptable, "", "", "MIN_NEAR_DIST; MEAN_NEAR_DIST; MAX_NEAR_DIST")
                for q in metoprof_searchrows:
                    mindist = q.MIN_NEAR_DIST
                    meandist = q.MEAN_NEAR_DIST
                    maxdist = q.MAX_NEAR_DIST
                        
                # Create search cursor to insert new data into the table
                metoprof_cur = arcpy.InsertCursor(metoprof_tbl)
                                    
                # Insert row with key statistics
                insert_out_row(metoprof_cur, "ME", str(professional))
        
        del metoprof_searchrows, metoprof_cur, q, metoprof_tbl
        
        # Clean up temp feature classes
        clean_up()
        
    print "Done with me-to-professional.  Beginning professional-to-professional:"
    
    
    '''
    # Cycle through and compare each professionally-delineated shoreline to all other professional shorelines
    '''
    summary_tbl = path + str(location) + '_professional_summary' 
    if not arcpy.Exists(summary_tbl):
        arcpy.CreateTable_management(path, str(location) + '_professional_summary')
        arcpy.AddField_management(summary_tbl, "FROM_PROF", "TEXT", "#", "#", "25")
        arcpy.AddField_management(summary_tbl, "TO_PROF", "TEXT", "#", "#", "25")
        arcpy.AddField_management(summary_tbl, "YEAR", "SHORT")
        arcpy.AddField_management(summary_tbl, "MEAN_DIST", "FLOAT", "10","10","20")
    
    out_table = path + str(location) + '_profTOprof'
        
    # Check and possibly create output .dbf table
    if arcpy.Exists(out_table):
        arcpy.Delete_management(out_table)
    create_out_table(path, location, '_profTOprof')
    
    for year in years:
        for fromprofessional in professionals:
            inshore = path + str(location) + '_shoreline_' + str(year) + '_' + fromprofessional
            
            if arcpy.Exists(inshore):
                # Convert shoreline verticies to points to calculate minimum and mean distances
                arcpy.FeatureVerticesToPoints_management(inshore, tempvert, "ALL")
                
                for toprofessional in professionals:
                    if toprofessional <> fromprofessional:
                        print str(fromprofessional) + ' -- to -- ' + str(toprofessional) + ' ' + str(year)
                        adjacentshore = path + str(location) + '_shoreline_' + str(year) + '_' + toprofessional
                                
                        # Perform NEAR analysis on verticies of base shoreline and determine the min and mean distances
                        arcpy.Near_analysis(tempvert,adjacentshore,"1000 Meters","NO_LOCATION","NO_ANGLE")
                        arcpy.Statistics_analysis(tempvert,temptable,"NEAR_DIST MIN;NEAR_DIST MEAN;NEAR_DIST MAX","#")
                                
                        # Search cursors used to define minimum and mean distance values
                        searchrows = arcpy.SearchCursor(temptable, "", "", "MIN_NEAR_DIST; MEAN_NEAR_DIST; MAX_NEAR_DIST")
                        for r in searchrows:
                            mindist = r.MIN_NEAR_DIST
                            meandist = r.MEAN_NEAR_DIST
                            maxdist = r.MAX_NEAR_DIST
                        
                        # Create search cursor to insert new data into the table
                        cur = arcpy.InsertCursor(out_table)
                                    
                        # Insert row with key statistics
                        insert_out_row(cur, str(fromprofessional), str(toprofessional))
            
                        # Calculate overall average distance between shorelines for all three professionals
                        arcpy.Statistics_analysis(out_table, tmp, "MEAN_DIST MEAN", "#")
                        
                        # Search for values to insert into summary_tbl
                        sumcur_search = arcpy.SearchCursor(tmp, "", "", "MEAN_MEAN_DIST")
                        for f in sumcur_search:
                            summeandist = f.MEAN_MEAN_DIST
                        
                        # Insert appropriate values into professional summary table
                        sumcur_insert = arcpy.InsertCursor(summary_tbl)
                        
                        sumrow = sumcur_insert.newRow()
                        sumrow.FROM_PROF = str(fromprofessional)
                        sumrow.TO_PROF = str(toprofessional)
                        sumrow.YEAR = year
                        sumrow.MEAN_DIST = summeandist
                        sumcur_insert.insertRow(sumrow)
        
    del sumcur_search, sumcur_insert, sumrow, searchrows, cur, r

    # Clean up temp files
    clean_up()

elapsed_time = time.time() - start_time
if elapsed_time > 60:
    print "Elapsed time: " + str(elapsed_time) + ' seconds'
elif elapsed_time <= 60:
    print "Elapsed time: " + str(elapsed_time/60) + ' minutes'
elif elapsed_time <= 3600:
    print "Elapsed time: " + str(elapsed_time/3600) + ' hours'