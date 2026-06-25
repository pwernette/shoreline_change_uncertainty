'''
Created on 02 February 2012

@author: Phil Wernette

Updated: 12 March, 2012

This script is designed to do a comprehensive epsilon bands analysis for each research site. It loops through all of the specified
locations and years at each of the specified confidence levels. Each year's shoreline at a given site is analyzed from and to all other
shorelines at the same site. The results of these analyses are output into the same geodatabase as the shorelines themselves.

CFOR MORE INFORMATION ABOUT MEASURING THE DISTANCE BETWEEN TWO LINEAR FEATURES:
http://forums.arcgis.com/threads/47780-Distance-between-two-linear-features

NOTES:
    1: Shorelines and transects for all four sites must be stored in a common geodatabase
    2: Shoreline feature classes must follow the naming convention:
        name = (location)_shoreline_(year)    example: 'alcona_shoreline_1938'
    3. Transect feature classes must follow the naming convention:
        name = (location)_transects           example: 'alcona_transects'
    3: Before running script be sure that the locations and years arrays are complete and consistent with the feature classes present.
'''

import time
import arcpy
from arcpy import env
env.overwriteOutput = True

# Defines function to generate the output table in the specified geodatabase
def create_out_table(outpath, loc):
    outtbl = path + loc + '_transect_analysis'
    arcpy.CreateTable_management(outpath, str(loc) + '_transect_analysis')
    arcpy.AddField_management(outtbl, "TRANSECT_ID", "TEXT", "#", "#", "20")
    arcpy.AddField_management(outtbl, "YEAR", "SHORT")
    arcpy.AddField_management(outtbl, "DISTANCE", "FLOAT", "10", "10", "20")
    del outpath, loc, outtbl
    
def create_out_table_prof(outpath, loc):
    outtbl = outpath + loc + '_transect_analysis_professional'
    arcpy.CreateTable_management(outpath, str(loc) + '_transect_analysis_professional')
    arcpy.AddField_management(outtbl, "SITE", "TEXT", "#", "#", "20")
    arcpy.AddField_management(outtbl, "YEAR", "SHORT")
    arcpy.AddField_management(outtbl, "TRANSECT_ID", "TEXT", "#", "#", "20")
    arcpy.AddField_management(outtbl, "PROFESSIONAL", "TEXT", "#", "#", "20")
    arcpy.AddField_management(outtbl, "DISTANCE", "FLOAT", "10", "10", "20")
    del outpath, loc, outtbl

# Defines the function to calculate, print, and export the elapsed time for a site
def elapsed_time_out(loc, loc_elapsed):
    if loc_elapsed < 60:
        print 'Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed) + ' seconds'
        f.write('Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed) + ' seconds\n')
    elif loc_elapsed >= 60 and loc_elapsed < 3600:
        print 'Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed/60) + ' minutes'
        f.write('Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed) + ' seconds\n')
    elif loc_elapsed >= 3600:
        print 'Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed/3600) + ' hours'
        f.write('Elapsed time for ' + str(loc) + ' - ' + str(loc_elapsed/3600) + ' hours\n')
    del loc, loc_elapsed

# Cleans up all temp feature classes that were generated
def clean_up():
    if arcpy.Exists(tempvert):
        arcpy.Delete_management(tempvert)
    if arcpy.Exists(temptable):
        arcpy.Delete_management(temptable)
    if arcpy.Exists(temproute):
        arcpy.Delete_management(temproute)

path = 'C:/Users/Phil/Documents/ArcGIS/Default.gdb/' # Geodatabase pathname
outlog_path = 'C:/Users/Phil/Documents/Geography MS/analysis/' # Output log file location

shorelinebuffer = path + 'shorelinebuffer'
tempvert = path + 'tempshorelineverticies'
temproute = path + 'temptransectroute'
temptable = path + 'temptable'

# List of professional shoreline delineations to analyze
professionals = ['acmoody','goodwin','lusch']

# List of the four location to be assessed
locations = ['alcona','allegan','manistee','sanilac']

# Corresponding list of years to be analyzed for each site
start_year = 1938
end_year = 2010
year_increment = 1
years = range(start_year,end_year + 1,year_increment)
#alcona_years = [1938,1952,1963,1979,1992,1998,2005,2009,2010]
#allegan_years = [1938,1950,1960,1967,1974,1998,2005,2009,2010]
#manistee_years = [1938,1952,1965,1973,1992,1998,2005,2009,2010]
#sanilac_years = [1941,1955,1963,1982,1998,2005,2009,2010]

alcona_skip = True
allegan_skip = True
manistee_skip = True
sanilac_skip = True
profes_skip = False

# Defines the beginning end of the transects
alcona_dir = "UPPER_LEFT"
allegan_dir = "UPPER_RIGHT"
manistee_dir = "UPPER_RIGHT"
sanilac_dir = "UPPER_LEFT"
profes_dir = "UPPER_LEFT"

start_time = time.time() 

for location in locations:
    '''
    ######################## ALCONA COUNTY ########################
    '''
    if location == 'alcona':
        if not alcona_skip:
            print "Beginning " + str(location) + ' analysis'
            location_start = time.time() # Start timer
            
            out_table = path + location + '_transect_analysis'
            
            # Generate output log .txt file
            f = open(outlog_path + str(location) + '_transect_analysis_log.txt','w')
            f.write('Site: ' + str(location) + '\n')
            f.write('site | year | transect | distance\n')
            
            #Check to see if the output table already exists (delete it, if it does)
            if arcpy.Exists(out_table):
                arcpy.Delete_management(out_table)
            create_out_table(path, location)
            
            # Transects for each individual research site
            transects = path + str(location) + '_transects'
                
            # Convert starting points of transects to point feature class
            if arcpy.Exists(temproute):
                arcpy.Delete_management(temproute)
            arcpy.CreateRoutes_lr(transects, "TRANSECT_ID", temproute, "LENGTH", coordinate_priority=alcona_dir)
           
            # List of years in site to analyze from
            #years = alcona_years
            
            # Loop through all the years for any given site
            for year in years:
                toshore = path + location + '_shoreline_' + str(year)
            
                if arcpy.Exists(toshore):
                    print str(location) + ' - ' + str(year)
                    
                    # Create search cursor to insert new data into the table
                    ins_cur = arcpy.InsertCursor(out_table)
                    
                    # Convert shoreline verticies to points to calculate minimum and mean distances
                    arcpy.Intersect_analysis([toshore, transects], tempvert, "ONLY_FID", output_type="POINT")
                    
                    # Calculate the distance of the shoreling along each transect
                    arcpy.LocateFeaturesAlongRoutes_lr(tempvert, temproute, "TRANSECT_ID", "100 Meters", temptable, "RID POINT MEAS", "FIRST", "DISTANCE", "ZERO", "FIELDS", "M_DIRECTON")
                    
                    # Initiate Search Cursor to cycle through the linear referencing output table
                    search_cur = arcpy.SearchCursor(temptable)
                    
                    for s in search_cur:
                        tran_id = s.RID
                        dist = s.MEAS
                            
                        r = ins_cur.newRow()
                        r.TRANSECT_ID = str(tran_id)
                        r.YEAR = str(year)
                        r.DISTANCE = dist
                        ins_cur.insertRow(r)
                            
                        f.write(str(location) + '|' + str(year) + '|' + str(tran_id) + '|' + str(dist) + '\n')
                
            # Calculate exapsed time for the site analysis                    
            location_elapsed = time.time() - location_start
            
            # Output duration information to output log file and print it on screen
            elapsed_time_out(location, location_elapsed)
            
            # Close output log text file
            f.close()
            
            # Clean up temp files
            clean_up()
                
            del ins_cur, search_cur, toshore, f, transects, location_start, location_elapsed, out_table


        if not profes_skip:
            print "Beginning " + str(location) + ' PROFESSIONAL analysis'
            location_start = time.time() # Start timer
            
            out_table = path + location + '_transect_analysis_professional'
            
            # Generate output log .txt file
            f = open(outlog_path + str(location) + '_transect_analysis_log_professional.txt','w')
            f.write('Site: ' + str(location) + '\n')
            f.write('site | year | transect | professional | distance\n')
            
            #Check to see if the output table already exists (delete it, if it does)
            if arcpy.Exists(out_table):
                arcpy.Delete_management(out_table)
            create_out_table_prof(path, location)
            
            # Transects for each individual research site
            transects = path + str(location) + '_transects'
                
            # Convert starting points of transects to point feature class
            if arcpy.Exists(temproute):
                arcpy.Delete_management(temproute)
            arcpy.CreateRoutes_lr(transects, "TRANSECT_ID", temproute, "LENGTH", coordinate_priority=profes_dir)
           
            # List of years in site to analyze from
            #years = alcona_years
            
            # Loop through all the years for any given site
            for year in years:
                for professional in professionals:
                    toshore = path + str(location) + '_shoreline_' + str(year) + '_' + str(professional)
                
                    if arcpy.Exists(toshore):
                        print str(location) + ' - ' + str(year)
                        
                        # Create search cursor to insert new data into the table
                        ins_cur = arcpy.InsertCursor(out_table)
                        
                        # Convert shoreline verticies to points to calculate minimum and mean distances
                        arcpy.Intersect_analysis([toshore, transects], tempvert, "ONLY_FID", output_type="POINT")
                        
                        # Calculate the distance of the shoreling along each transect
                        arcpy.LocateFeaturesAlongRoutes_lr(tempvert, temproute, "TRANSECT_ID", "100 Meters", temptable, "RID POINT MEAS", "FIRST", "DISTANCE", "ZERO", "FIELDS", "M_DIRECTON")
                        
                        # Initiate Search Cursor to cycle through the linear referencing output table
                        search_cur = arcpy.SearchCursor(temptable)
                        
                        for s in search_cur:
                            tran_id = s.RID
                            dist = s.MEAS
                            
                            r = ins_cur.newRow()
                            r.SITE = str(location)
                            r.YEAR = str(year)
                            r.TRANSECT_ID = str(tran_id)
                            r.PROFESSIONAL = str(professional)
                            r.DISTANCE = dist
                            ins_cur.insertRow(r)
                            
                            f.write(str(location) + '|' + str(year) + '|' + str(tran_id) + '|' + str(professional) + '|' + str(dist) + '\n')
            
            # Calculate exapsed time for the site analysis                    
            location_elapsed = time.time() - location_start
            
            # Output duration information to output log file and print it on screen
            elapsed_time_out(location, location_elapsed)
            
            # Close output log text file
            f.close()
            
            # Clean up temp files
            clean_up()
                
            del ins_cur, search_cur, toshore, f, transects, location_start, location_elapsed, out_table
    
    '''
    ######################## ALLEGAN COUNTY ########################
    '''    
    if location == 'allegan':
        if not allegan_skip:
            print "Beginning " + str(location) + ' analysis'
            location_start = time.time() # Start timer
            
            out_table = path + location + '_transect_analysis'
            
            # Generate output log .txt file
            f = open(outlog_path + str(location) + '_transect_analysis_log.txt','w')
            f.write('Site: ' + str(location) + '\n')
            f.write('site | year | transect | distance\n')
            
            #Check to see if the output table already exists (delete it, if it does)
            if arcpy.Exists(out_table):
                arcpy.Delete_management(out_table)
            create_out_table(path, location)
            
            # Transects for each individual research site
            transects = path + str(location) + '_transects'
                
            # Convert starting points of transects to point feature class
            if arcpy.Exists(temproute):
                arcpy.Delete_management(temproute)
            arcpy.CreateRoutes_lr(transects, "TRANSECT_ID", temproute, "LENGTH", coordinate_priority=allegan_dir)
           
            # List of years in site to analyze from
            #years = allegan_years
            
            # Loop through all the years for any given site
            for year in years:
                toshore = path + location + '_shoreline_' + str(year)
            
                if arcpy.Exists(toshore):
                    print str(location) + ' - ' + str(year)
                    
                    # Create search cursor to insert new data into the table
                    ins_cur = arcpy.InsertCursor(out_table)
                    
                    # Convert shoreline verticies to points to calculate minimum and mean distances
                    arcpy.Intersect_analysis([toshore, transects], tempvert, "ONLY_FID", output_type="POINT")
                    
                    # Calculate the distance of the shoreling along each transect
                    arcpy.LocateFeaturesAlongRoutes_lr(tempvert, temproute, "TRANSECT_ID", "100 Meters", temptable, "RID POINT MEAS", "FIRST", "DISTANCE", "ZERO", "FIELDS", "M_DIRECTON")
                    
                    # Initiate Search Cursor to cycle through the linear referencing output table
                    search_cur = arcpy.SearchCursor(temptable)
                    
                    for s in search_cur:
                        tran_id = s.RID
                        dist = s.MEAS
                        
                        r = ins_cur.newRow()
                        r.TRANSECT_ID = str(tran_id)
                        r.YEAR = str(year)
                        r.DISTANCE = dist
                        ins_cur.insertRow(r)
                        
                        f.write(str(location) + '|' + str(year) + '|' + str(tran_id) + '|' + str(dist) + '\n')
            
            # Calculate exapsed time for the site analysis                    
            location_elapsed = time.time() - location_start
            
            # Output duration information to output log file and print it on screen
            elapsed_time_out(location, location_elapsed)
            
            # Close output log text file
            f.close()
            
            # Clean up temp files
            clean_up()
                
            del ins_cur, search_cur, toshore, f, transects, location_start, location_elapsed, out_table
            
    '''
    ######################## MANISTEE COUNTY ########################
    '''
    if location == 'manistee':
        if not manistee_skip:
            print "Beginning " + str(location) + ' analysis'
            location_start = time.time() # Start timer
            
            out_table = path + location + '_transect_analysis'
            
            # Generate output log .txt file
            f = open(outlog_path + str(location) + '_transect_analysis_log.txt','w')
            f.write('Site: ' + str(location) + '\n')
            f.write('site | year | transect | distance\n')
            
            #Check to see if the output table already exists (delete it, if it does)
            if arcpy.Exists(out_table):
                arcpy.Delete_management(out_table)
            create_out_table(path, location)
            
            # Transects for each individual research site
            transects = path + str(location) + '_transects'
                
            # Convert starting points of transects to point feature class
            if arcpy.Exists(temproute):
                arcpy.Delete_management(temproute)
            arcpy.CreateRoutes_lr(transects, "TRANSECT_ID", temproute, "LENGTH", coordinate_priority=manistee_dir)
           
            # List of years in site to analyze from
            #years = manistee_years
            
            # Loop through all the years for any given site
            for year in years:
                toshore = path + location + '_shoreline_' + str(year)
            
                if arcpy.Exists(toshore):
                    print str(location) + ' - ' + str(year)
                    
                    # Create search cursor to insert new data into the table
                    ins_cur = arcpy.InsertCursor(out_table)
                    
                    # Convert shoreline verticies to points to calculate minimum and mean distances
                    arcpy.Intersect_analysis([toshore, transects], tempvert, "ONLY_FID", output_type="POINT")
                    
                    # Calculate the distance of the shoreling along each transect
                    arcpy.LocateFeaturesAlongRoutes_lr(tempvert, temproute, "TRANSECT_ID", "100 Meters", temptable, "RID POINT MEAS", "FIRST", "DISTANCE", "ZERO", "FIELDS", "M_DIRECTON")
                    
                    # Initiate Search Cursor to cycle through the linear referencing output table
                    search_cur = arcpy.SearchCursor(temptable)
                    
                    for s in search_cur:
                        tran_id = s.RID
                        dist = s.MEAS
                        
                        r = ins_cur.newRow()
                        r.TRANSECT_ID = str(tran_id)
                        r.YEAR = str(year)
                        r.DISTANCE = dist
                        ins_cur.insertRow(r)
                        
                        f.write(str(location) + '|' + str(year) + '|' + str(tran_id) + '|' + str(dist) + '\n')
            
            # Calculate exapsed time for the site analysis                    
            location_elapsed = time.time() - location_start
            
            # Output duration information to output log file and print it on screen
            elapsed_time_out(location, location_elapsed)
            
            # Close output log text file
            f.close()
            
            # Clean up temp files
            clean_up()
                
            del ins_cur, search_cur, toshore, f, transects, location_start, location_elapsed, out_table
            
    '''
    ######################## SANILAC COUNTY ########################
    '''
    if location == 'sanilac':
        if not sanilac_skip:
            print "Beginning " + str(location) + ' analysis'
            location_start = time.time() # Start timer
            
            out_table = path + location + '_transect_analysis'
            
            # Generate output log .txt file
            f = open(outlog_path + str(location) + '_transect_analysis_log.txt','w')
            f.write('Site: ' + str(location) + '\n')
            f.write('site | year | transect | distance\n')
            
            #Check to see if the output table already exists (delete it, if it does)
            if arcpy.Exists(out_table):
                arcpy.Delete_management(out_table)
            create_out_table(path, location)
            
            # Transects for each individual research site
            transects = path + str(location) + '_transects'
                
            # Convert starting points of transects to point feature class
            if arcpy.Exists(temproute):
                arcpy.Delete_management(temproute)
            arcpy.CreateRoutes_lr(transects, "TRANSECT_ID", temproute, "LENGTH", coordinate_priority=sanilac_dir)
           
            # List of years in site to analyze from
            #years = sanilac_years
            
            # Loop through all the years for any given site
            for year in years:
                toshore = path + location + '_shoreline_' + str(year)
            
                if arcpy.Exists(toshore):
                    print str(location) + ' - ' + str(year)
                    
                    # Create search cursor to insert new data into the table
                    ins_cur = arcpy.InsertCursor(out_table)
                    
                    # Convert shoreline verticies to points to calculate minimum and mean distances
                    arcpy.Intersect_analysis([toshore, transects], tempvert, "ONLY_FID", output_type="POINT")
                    
                    # Calculate the distance of the shoreling along each transect
                    arcpy.LocateFeaturesAlongRoutes_lr(tempvert, temproute, "TRANSECT_ID", "100 Meters", temptable, "RID POINT MEAS", "FIRST", "DISTANCE", "ZERO", "FIELDS", "M_DIRECTON")
                    
                    # Initiate Search Cursor to cycle through the linear referencing output table
                    search_cur = arcpy.SearchCursor(temptable)
                    
                    for s in search_cur:
                        tran_id = s.RID
                        dist = s.MEAS
                        
                        r = ins_cur.newRow()
                        r.TRANSECT_ID = str(tran_id)
                        r.YEAR = str(year)
                        r.DISTANCE = dist
                        ins_cur.insertRow(r)
                        
                        f.write(str(location) + '|' + str(year) + '|' + str(tran_id) + '|' + str(dist) + '\n')
            
            # Calculate exapsed time for the site analysis                    
            location_elapsed = time.time() - location_start
            
            # Output duration information to output log file and print it on screen
            elapsed_time_out(location, location_elapsed)
            
            # Close output log text file
            f.close()
            
            # Clean up temp files
            clean_up()
                
            del ins_cur, search_cur, toshore, f, transects, location_start, location_elapsed, out_table

elapsed_time = time.time() - start_time

if elapsed_time < 60:
    print "Elapsed time: " + str(elapsed_time) + ' seconds'
elif elapsed_time >= 60 and elapsed_time < 3600:
    print "Elapsed time: " + str(elapsed_time/60) + ' minutes'
elif elapsed_time >= 3600:
    print "Elapsed time: " + str(elapsed_time/3600) + ' hours'