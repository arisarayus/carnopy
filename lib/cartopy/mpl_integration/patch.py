# (C) British Crown Copyright 2011 - 2012, Met Office
#
# This file is part of cartopy.
#
# cartopy is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the
# Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# cartopy is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with cartopy.  If not, see <http://www.gnu.org/licenses/>.


"""
Provides geos <-> mpl path support.

Please note: This code needs a significant spruce and review.
  
"""

import numpy as np
import matplotlib.path
from matplotlib.path import Path
from shapely.geometry.collection import GeometryCollection
from shapely.geometry.linestring import LineString
from shapely.geometry.point import Point
from shapely.geometry.polygon import Polygon
from shapely.geometry.multilinestring import MultiLineString
from shapely.geometry.multipoint import MultiPoint
from shapely.geometry.multipolygon import MultiPolygon


def geos_to_path(shape):
    """Return a list of paths created from this shape."""
    # Iterate through lists/tuples of shapes, concatenating the
    # results.
    if isinstance(shape, (list, tuple)):
        paths = []
        for shp in shape:
            paths.extend(geos_to_path(shp))
        return paths

    if isinstance(shape, (LineString, Point)):
        return [Path(np.vstack(shape.xy).T)]
    elif isinstance(shape, Polygon):
        def poly_codes(poly):
            codes = np.ones(len(poly.xy[0])) * Path.LINETO
            codes[0] = Path.MOVETO
            return codes
        
        vertices = np.concatenate([np.array(shape.exterior.xy)] +
                                  [np.array(ring.xy) for ring in
                                   shape.interiors], 1).T
        codes = np.concatenate([poly_codes(shape.exterior)] +
                               [poly_codes(ring) for ring in shape.interiors])
        return [Path(vertices, codes)]
    elif isinstance(shape, (MultiPolygon, GeometryCollection, MultiLineString,
                            MultiPoint)):
        paths = []
        for geom in shape.geoms:
            paths.extend(geos_to_path(geom))
        return paths
    elif hasattr(shape, '_as_mpl_path'):
        vertices, codes = shape._as_mpl_path()
        return [Path(vertices, codes)]
    else:
        raise ValueError('Unsupported shape type {}.'.format(type(shape)))


def path_segments(path, transform=None, remove_nans=False, clip=None,
                  quantize=False, simplify=False, curves=False,
                  stroke_width=1.0, snap=False):
    """See path.iter_segments. Vectorised version of that."""
    # XXX assigned to avoid a ValueError inside the mpl C code...
    a = transform, remove_nans, clip, quantize, simplify, curves

    # Series of cleanups and conversions to the path e.g. it
    # can convert curved segments to line segments.
    vertices, codes = matplotlib.path.cleanup_path(path, transform,
                                                   remove_nans, clip,
                                                   snap, stroke_width,
                                                   simplify, curves)
    
    # Remove the final vertex (with code 0)
    return vertices[:-1, :], codes[:-1]


def path_to_geos(path):
    """
    """
    # Convert path into numpy array of vertices (and associated codes)
    path_verts, path_codes = path_segments(path, curves=False)
    
    # Split into subarrays such that each subarray consists of connected
    # line segments based on the start of each one being marked by a
    # matplotlib MOVETO code.
    verts_split_inds = np.where(path_codes == Path.MOVETO)[0]
    verts_split = np.split(path_verts, verts_split_inds)
    codes_split = np.split(path_codes, verts_split_inds)
    
    # Iterate through the vertices generating a list of
    # (external_geom, [internal_polygons]) tuples.
    collection = []
    for path_verts, path_codes in zip(verts_split, codes_split):
        if len(path_verts) == 0:
            continue

        # XXX A path can be given which does not end with close poly, in that
        # situation, we have to guess?
        # XXX Implement a point
                
        if path_verts.shape[0] > 2 and (path_codes[-1] == Path.CLOSEPOLY or
                                        all(path_verts[0, :] == path_verts[-1, :])):
            if path_codes[-1] == Path.CLOSEPOLY:
                geom = Polygon(path_verts[:-1, :])
            else:
                geom = Polygon(path_verts)
        else:
            geom = LineString(path_verts)

        # If geom is a Polygon and is contained within the last geom in collection,
        # add it to its list of internal polygons, otherwise simple append it as a
        # new external geom.
        if (len(collection) > 0 and 
                 isinstance(collection[-1][0], Polygon) and
                 isinstance(geom, Polygon) and
                 collection[-1][0].contains(geom.exterior)):
            collection[-1][1].append(geom.exterior)
        else:
            collection.append((geom, []))
    
    # Convert each (external_geom, [internal_polygons]) pair into a
    # a shapely Polygon that encapsulates the internal polygons, if the
    # external geom is a LineSting leave it alone.
    geom_collection = []
    for external_geom, internal_polys in collection:
        if internal_polys:
            # XXX worry about islands within lakes
            geom = Polygon(external_geom.exterior, internal_polys)
        else:
            geom = external_geom
        geom_collection.append(geom)
    
    # If the geom_collection only contains LineStrings combine them
    # into a single MultiLinestring.
    if geom_collection and all(isinstance(geom, LineString) for
                               geom in geom_collection):
        geom_collection = [MultiLineString(geom_collection)]

    # Remove any zero area Polygons
    result = filter(lambda geom: (isinstance(geom, Polygon) and geom.area != 0) or
                    not isinstance(geom, Polygon), geom_collection)
    
    return result
