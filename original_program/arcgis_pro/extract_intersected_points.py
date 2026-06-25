'''
Created on May 11, 2012

@author: Phil
'''

import arcpy
from arcpy import env
env.overwriteOutput = True

path = 'C:/Users/Phil/Documents/ArcGIS/Default.gdb/' # Geodatabase pathname
outpath = 'C:/Users/Phil/Documents/ArcGIS/Identity_data.gdb/' # Output geodatabase
outlog_path = 'C:/Users/Phil/Documents/Geography MS/analysis/' # Output log file location

# List of the four location to be assessed
locations = ['alcona','allegan','manistee','sanilac']

# Specify the beginning year and ending year and increment
start_year = 1938
end_year = 2010
increment = 1

alcona_skip = False
allegan_skip = False
manistee_skip = False
sanilac_skip = False

# Generates array with all possible years
years = range(start_year,end_year + 1,increment)

for location in locations:
    # Create new output text file to log results in
    f = open(outlog_path + 'INTERSECT_POINTS_' + str(location) + '.txt','w')
    f.write('transect_id | year | x_coord | y_coord\n')
    
    transects = path + location + '_transects'
    
    if arcpy.Exists(transects):
        print "Transects found for: " + str(location)
        for year in years:
            shoreline = path + location + '_shoreline_' + str(year)
            
            if arcpy.Exists(shoreline):
                print "Starting shoreline for: " + str(year)
                outloc = outpath + location + '_intersect_' + str(year)
                
                #Intersect shoreline with transects
                arcpy.Intersect_analysis([shoreline, transects],outloc,"ALL",output_type="POINT")
                
                # Calculate XY coordinates of intersected points
                print "Adding XY coordinates..."
                arcpy.AddXY_management(outloc)
                
                # Create new search cursor to iterate through new feature class
                search_cur = arcpy.SearchCursor(outloc)
                
                print "Writing to output log file..."
                for s in search_cur:
                    transectid = s.TRANSECT_ID
                    transectno = s.TRANSECT_NO
                    ptx = s.POINT_X
                    pty = s.POINT_Y
                    
                    f.write(str(transectno) + '|' + str(year) + '|' + str(ptx) + '|' + str(pty) + '\n')
                
    f.close()
    del(search_cur, f, outloc, ptx, pty, transectid, transectno)