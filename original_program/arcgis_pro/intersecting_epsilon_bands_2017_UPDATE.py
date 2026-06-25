'''
Created on May 23, 2012

Copyright 2012: Phil Wernette

This script is designed to do a comprehensive epsilon bands analysis for each research site. It loops through all of the specified
locations and years at each site. The steps are:
1) Draw buffer A around shoreline A (radius is based on the uncertainty for shoreline A)
2) Draw buffer B around shoreline B (radius is based on the uncertainty for shoreline B)
3) Intersect buffer A and buffer B
4) Calculate area of buffer A, buffer B, intersection of AB
5) Calculate the intersecting proportion by: (area of AB)/((area of A)+(area of B))

The uncertainty for a shoreline is stored as the "UNCERTAINTY" attribute within the feature class.

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
from arcpy import env
env.overwriteOutput = T

def create_out_table(outpath, loc):
    # This function creates a new output table in ArcGIS.
    # The new table will be populated later in the process.
    outtbl = outpath + loc + 'OverlappingBufferTable'
    arcpy.CreateTable_management(outpath, str(loc) + 'OverlappingBufferTable')
    arcpy.AddField_management(outtbl, "SITE", "TEXT", "#", "#", "20")
    arcpy.AddField_management(outtbl, "YEAR_A", "SHORT")
    arcpy.AddField_management(outtbl, "YEAR_B", "SHORT")
    arcpy.AddField_management(outtbl, "AREA_A", "FLOAT", "10","10","20")
    arcpy.AddField_management(outtbl, "AREA_B", "FLOAT", "10","10","20")
    arcpy.AddField_management(outtbl, "AREA_AB_OVERLAP", "FLOAT", "10","10","20")
    arcpy.AddField_management(outtbl, "PROP_AB_OVERLAP", "FLOAT", "10", "10", "20")
    arcpy.AddField_management(outtbl, "AREA_AB_TOTAL", "FLOAT", "10", "10", "20")
    del outpath, loc, outtbl

# DATA TO COLLECT:    site | year_A | year_B | area_A | area_B | area_AB_overlap | prop_AB_overlap | area_AB_total

def insert_out_row(insert_cursor):
    # This function is designed to insert a new row of data into the output table in ArcGIS
    row = insert_cursor.newRow()
    row.SITE = str(l)
    row.YEAR_A = a
    row.YEAR_B = b
    row.AREA_A = area_a
    row.AREA_B = area_b
    row.AREA_AB_OVERLAP = area_ab
    row.PROP_AB_OVERLAP = prop_ab
    row.AREA_AB_TOTAL = a_and_b_area
    insert_cursor.insertRow(row)
    del row
    
def elapsed_time_out(loc, loc_elapsed):
    if loc_elapsed < 60:
        print 'Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed) + ' seconds'
    elif loc_elapsed >= 60 and loc_elapsed < 3600:
        print 'Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed/60) + ' minutes'
    elif loc_elapsed >= 3600:
        print 'Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed/3600) + ' hours'
    del loc, loc_elapsed
    
def clean_up(items):
    # This function is designed to search for and delete any feature class in the specified array
    for clean in items:
        if arcpy.Exists(clean):
            arcpy.Delete_management(clean)

# Paths where data is stored and saved throughout processing
path = 'D:/Documents/ArcGIS/Default.gdb/' # Geodatabase pathname
outlog_path = 'D:/Dropbox/Geography MS/analysis/' # Output log file location
overlap_gdb = 'D:/Documents/ArcGIS/Epsilon_analysis_OVERLAP.gdb/' # Geodatabase with overlapping segments
# diff_gdb = 'C:/Users/Phil/Documents/ArcGIS/Epsilon_analysis_NONoverlap.gdb/'

# List of temporary feature classes that will be used in the processing
buffer_a = path + 'shorelinebuffera'
buffer_b = path + 'shorelinebufferb'
a_and_b = path + 'shorelinebuffersab'
ab_intersect = path + 'shorelinebuffer_AB'

# List of the four location to be assessed
locations = ['alcona','allegan','manistee','sanilac']

# Corresponding list of years to be analyzed for each site
start_year = 1938
end_year = 2010
year_increment = 1
years_a = range(start_year, end_year + 1, year_increment)
years_b = range(start_year + 1, end_year + 1, year_increment)

''' Toggle option to export the intersected areas to individual feature classes
   T = export the overlapping area    F = do NOT export the overlapping area'''
export_intersect = T

# List of files to delete at the conclusion of the script
clean_list = [buffer_a, buffer_b, ab_intersect, a_and_b]

start_time = time.time() #Start the timer for the overall processing

for l in locations:
    location_start = time.time()
    
    out_table = path + l + 'OverlappingBufferTable'
            
    log = open(outlog_path + 'OVERLAPPING_BANDS_' + str(l) + '.txt','w')
    log.write('Site: ' + str(l) + '\n')
    log.write('site | year_A | year_B | area_A | area_B | area_AB_overlap | prop_AB_overlap | area_AB_total\n')
    
    #Check to see if the output table already exists (delete it, if it does)
    if arcpy.Exists(out_table):
        arcpy.Delete_management(out_table)
    create_out_table(path, l)
    
    # Create search cursor to insert new data into the table
    ins_cur = arcpy.InsertCursor(out_table)
    
    # Loop through all the years for any given site
    for a in years_a:
        # Define name of shoreline A
        shoreline_a = path + l + '_shoreline_' + str(a)
        
        if arcpy.Exists(shoreline_a):
            
            # Create search cursor to extract the shoreline uncertainty
            a_cur = arcpy.SearchCursor(shoreline_a)
            for c in a_cur:
                a_buf_rad = c.UNCERTAINTY
            '''
            shoreline_buffer = diff_gdb + l + '_shoreline_buffer_' + str(a)
            if arcpy.Exists(shoreline_buffer):
                arcpy.Delete_management(shoreline_buffer)
            arcpy.Buffer_analysis(shoreline_a, shoreline_buffer, a_buf_rad, dissolve_option="ALL")
            '''
            if arcpy.Exists(buffer_a):
                arcpy.Delete_management(buffer_a)
            arcpy.Buffer_analysis(shoreline_a, buffer_a, a_buf_rad, dissolve_option="ALL")
            
            # Calculate the area of buffer around shoreline A
            t = arcpy.Geometry()
            tgeometryList = arcpy.CopyFeatures_management(buffer_a, t)
            tarea = 0 #Sets default area to 0 before calculating the area
            for tgeometry in tgeometryList:
                tarea += tgeometry.area
            area_a = tarea
            
            for b in years_b:
                if b>a:
                    # Define name of shoreline B
                    shoreline_b = path + l + '_shoreline_' + str(b)

                    if arcpy.Exists(shoreline_b):
                        print ('Processing ' + str(l) + ' for years ' + str(a) + ' and ' + str(b))
                        
                        # Create search cursor to extract the shoreline uncertainty
                        b_cur = arcpy.SearchCursor(shoreline_b)
                        for d in b_cur:
                            b_buf_rad = d.UNCERTAINTY
                        
                        if arcpy.Exists(buffer_b):
                            arcpy.Delete_management(buffer_b)
                        arcpy.Buffer_analysis(shoreline_b, buffer_b, b_buf_rad, dissolve_option='ALL')
                        
                        # Calculate the area of buffer around shoreline B
                        s = arcpy.Geometry()
                        sgeometryList = arcpy.CopyFeatures_management(buffer_b, s)
                        sarea = 0 #Sets default area to 0 before calculating the area
                        for sgeometry in sgeometryList:
                            sarea += sgeometry.area
                        area_b = sarea
                        
                        # Intersect the two shoreline buffers
                        if arcpy.Exists(ab_intersect):
                            arcpy.Delete_management(ab_intersect)
                        arcpy.Intersect_analysis([buffer_a, buffer_b], ab_intersect, "ONLY_FID")
                        if export_intersect:
                            arcpy.FeatureClassToFeatureClass_conversion(ab_intersect, overlap_gdb, str(l) + '_overlap_' + str(a) + '_' + str(b))
                            
                        # Calculate the intersected AB area
                        r = arcpy.Geometry()
                        rgeometryList = arcpy.CopyFeatures_management(ab_intersect, r)
                        rarea = 0 #Sets default area to 0 before calculating the combined area
                        for rgeometry in rgeometryList:
                            rarea += rgeometry.area
                        area_ab = rarea
                        
                        # Union areas A and B and calculte the combined area of A and B
                        arcpy.Union_analysis([buffer_a, buffer_b], a_and_b) # Join areas A and B
                        
                        u = arcpy.Geometry()
                        ugeometryList = arcpy.CopyFeatures_management(a_and_b, u)
                        uarea = 0 #Sets default area to 0 before calculating the combined area
                        for ugeometry in ugeometryList:
                            uarea += ugeometry.area
                        a_and_b_area = uarea
                        
                        prop_ab = area_ab/a_and_b_area
                        
                        insert_out_row(ins_cur)
                        
                        # Write results to pipe-delimited .csv file
                        log.write(str(l) + '|' + str(a) + '|' + str(b) + '|' + str(area_a) + '|' + str(area_b) + '|' + str(area_ab) + '|' + str(prop_ab) + '|' + str(a_and_b_area) + '\n')
    
    # Calculate elapsed time for the given location
    location_elapsed = time.time() - location_start
    
    # Print and Export Elapsed Time
    elapsed_time_out(l, location_elapsed)
    
    # Close oujtput files
    log.close()
    
    # Clean up temp files
    clean_up(clean_list)
    
    del a, b, area_a, area_b, area_ab, prop_ab, l, r, s, t, u, a_cur, b_cur, ins_cur, shoreline_a, shoreline_b

elapsed_time = time.time() - start_time

if elapsed_time < 60:
    print "Elapsed time: " + str(elapsed_time) + ' seconds'
elif elapsed_time >= 60 and elapsed_time < 3600:
    print "Elapsed time: " + str(elapsed_time/60) + ' minutes'
elif elapsed_time >= 3600:
    print "Elapsed time: " + str(elapsed_time/3600) + ' hours'
