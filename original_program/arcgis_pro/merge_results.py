'''
Created on Feb 29, 2012

@author: Phillipe Wernette, PhD
Director, Remote Sensing & GIS Research and Outreach Services (RS&GIS)
Michigan State University, East Lansing, MI 48823
pwernett@msu.edu
'''
import time
import arcpy
from arcpy import env
env.overwriteOutput = True

path = ''  # TODO: set path to your ArcGIS geodatabase # Geodatabase pathname
outlog_path = ''  # TODO: set path to your output log directory # Output log file location

shorelinebuffer = path + 'shorelinebuffer'
tempvert = path + 'tempshorelineverticies'
temproute = path + 'temptransectroute'
temptable = path + 'temptable'

# List of professional shoreline delineations to analyze
professionals = ['acmoody','goodwin','lusch']

# List of the four location to be assessed
locations = ['alcona','allegan','manistee','sanilac']

# Corresponding list of years to be analyzed for each site
alcona_years = [1938,1952,1963,1979,1992,1998,2005,2009,2010]
allegan_years = [1938,1950,1960,1967,1974,1998,2005,2009,2010]
manistee_years = [1938,1952,1965,1973,1992,1998,2005,2009,2010]
sanilac_years = [1941,1955,1963,1982,1998,2005,2009,2010]

alcona_skip = False
allegan_skip = True
manistee_skip = True
sanilac_skip = True

for location in locations:
    '''
    ######################## ALCONA COUNTY ########################
    '''
    if location == 'alcona':
        if not alcona_skip:
            print "Beginning " + str(location) + ' merge'
            
            in_tbl = path + location + '_transect_analysis'
            
            # Initialize search cursor
            search_cur = arcpy.SearchCursor(in_tbl)
            for s in search_cur:
                tran_id = s.TRANSECT_ID
                yr = s.YEAR
                dist = s.DISTANCE
            
            # List of years in site to analyze from
            years = alcona_years
            
            # Loop through all the years for any given site
            for year in years:
                if year == yr:
                    arcpy.AddField_management(in_tbl, 'TO_' + str(year), 'SHORT')
                   
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
            
            del ins_cur, search_cur, toshore, years, f, transects, location_start, location_elapsed, out_table