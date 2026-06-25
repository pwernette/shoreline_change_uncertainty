'''
Created on Feb 6, 2012

@author: Phil

Loops through all epsilon band output tables in geodatabase and copies the contents into a pipe-delimited .txt file
in the specified output folder.

NOTE: This will overwrite any existing files with the same output filename.
'''
import time
import arcpy
from arcpy import env
env.overwriteOutput = True

path = 'C:/Users/Phil/Documents/ArcGIS/Default.gdb/' # Geodatabase pathname
outlog_path = 'C:/Users/Phil/Documents/Geography MS/analysis/epsilon_band_results/' # Output log file location

# List of confidence levels to loop the analysis through
confidence_levels = [0.05,0.50,0.90,0.95]
#confidence_levels = [0.95]

# List of the four location to be assessed
locations = ['alcona','allegan','manistee','sanilac']

# Corresponding list of years to be analyzed for each site
alcona_years = [1938,1952,1963,1979,1992,1998,2005,2009,2010]
allegan_years = [1938,1950,1960,1967,1974,1998,2005,2009,2010]
manistee_years = [1938,1952,1965,1973,1992,1998,2005,2009,2010]
sanilac_years = [1941,1955,1963,1982,1998,2005,2009,2010]

for confidence_level in confidence_levels:
    # This is the the adjacent shoreline used to create the threshold
    #confidence_level = 0.05 # Amount in PROPORTION
    percent_threshold = str(confidence_level).split('.')[1]  #Amount in PERCENT
    
    #start_time = time.time() #Record how long it takes
    
    for location in locations:
        out_table = path + location + 'ShorelineBufferTable' + str(percent_threshold)
            
        log = open(outlog_path + str(location) + '_epsilon_bands_results' + str(percent_threshold) + '.txt','w')
        log.write('Site: ' + str(location) + '\n')
        log.write('Confidence Level: ' + str(confidence_level) + '\n')
        log.write('site | from_year | to_year | buffer_radius | threshold | observed_length | min_dist | mean_dist | max_dist\n')
        
        curs = arcpy.SearchCursor(out_table)
        
        for cur in curs:
            fromyear = cur.FROM_YEAR
            toyear = cur.TO_YEAR
            bufrad = cur.BUFFER_RADIUS
            threshold = cur.THRESHOLD
            obslength = cur.OBS_LENGTH
            mindist = cur.MIN_DIST
            meandist = cur.MEAN_DIST
            maxdist = cur.MAX_DIST
            
            log.write(str(location) + '|' + str(fromyear) + '|' + str(toyear) + '|' + str(bufrad) + '|' + str(threshold) + '|' + str(obslength) + '|' + str(mindist) + '|' + str(meandist) + '|' + str(maxdist) + '\n')
            
        log.close()