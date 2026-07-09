'''
Created on Sep 21, 2011

@author: Phillipe Wernette, PhD
Director, Remote Sensing & GIS Research and Outreach Services (RS&GIS)
Michigan State University, East Lansing, MI 48823
pwernett@msu.edu
'''
import arcpy
import arcpy.mapping
from arcpy import env
env.overwriteOutput = True

schema = ''  # TODO: set path to your ArcGIS geodatabase

alcona_years = ['1938','1952','1963','1979','1992','1998','2005','2009','2010']
allegan_years = ['1938','1950','1960','1967','1974','1998','2005','2009','2010']
manistee_years = ['1938','1952','1965','1973','1992','1998','2005','2009','2010']
sanilac_years = ['1941','1955','1963','1982','1998','2005','2009','2010']

sr = 'C:\Program Files (x86)\ArcGIS\Desktop10.0\Coordinate Systems\Projected Coordinate Systems\State Plane\NAD 1983 (Meters)\NAD 1983 StatePlane Michigan Central FIPS 2112 (Meters).prj'
sites = ['alcona','manistee','allegan','sanilac']
for site in sites:
    arcpy.CreateFeatureclass_management(schema, str(site) + "_shorelines", 'POLYLINE', spatial_reference=sr)
    arcpy.CreateFeatureclass_management(schema, str(site) + "_baseline", 'POLYLINE', spatial_reference=sr)
    if site == 'alcona':
        xs = alcona_years
        for x in xs:
            name = site + '_shoreline_' + x
            arcpy.CreateFeatureclass_management(schema, name, 'POLYLINE',spatial_reference=sr)
            print 'CREATED: ' + str(name)
        del xs, name
    elif site == 'allegan':
        xs = allegan_years
        for x in xs:
            name = site + '_shoreline_' + x
            arcpy.CreateFeatureclass_management(schema, name, 'POLYLINE', spatial_reference=sr)
            print 'CREATED: ' + str(name)
        del xs, name 
    elif site == 'manistee':
        xs = manistee_years
        for x in xs:
            name = site + '_shoreline_' + x
            arcpy.CreateFeatureclass_management(schema, name, 'POLYLINE', spatial_reference=sr)
            print 'CREATED: ' + str(name)
        del xs, name
    elif site == 'sanilac':
        xs = sanilac_years
        for x in xs:
            name = site + '_shoreline_' + x
            arcpy.CreateFeatureclass_management(schema, name, 'POLYLINE', spatial_reference=sr)
            print 'CREATED: ' + str(name)
        del xs, name
    else:
        print "No files could be exported. Check that files exist and script is accurate."

print "-----> DONE! <-----"