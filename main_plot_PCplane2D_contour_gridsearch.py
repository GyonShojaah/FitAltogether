import numpy as np
import sys
import corner
import datetime
import os

import emcee

import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.colors import LinearSegmentedColormap
from mpl_toolkits.axes_grid1 import make_axes_locatable


from scipy.interpolate import griddata

import prior
import reparameterize

import PCA
import shrinkwrap

import geometry


import multiprocessing
import functools


LOOP_MAX  = 10000
COUNT_MAX = 100

SEED_in  = 2015

deg2rad = np.pi/180.

LAMBDA_CORR_DEG = 30.
LAMBDA_CORR = LAMBDA_CORR_DEG * deg2rad



# GEOM = ( lat_o, lon_o, lat_s, lon_s, omega )
# GEOM = ( 0., 0., 0.,  90., 2.*np.pi )

N_SIDE   = 32
INFILE_DIR = 'mockdata/'
# INFILE = 'mockdata_45deg_time23_l`xreplc'
INFILE = 'mockdata_45deg_3types_redAmerica_t12_lc'
OUTFILE_DIR = 'PCplane/'

ALBDFILE = 'mockdata/mockdata_45deg_3types_redAmerica_t12_band_sp'
AREAFILE = 'mockdata/mockdata_45deg_3types_redAmerica_t12_factor'

VARAMP = 0.01

N_TYPE = 3
N_CPU  = 2
N_MCMC = 100

X_MIN = -0.2
X_MAX = 0.4
# X_NUM = 27
X_NUM = 15
Y_MIN = -0.2
Y_MAX = 0.8
Y_NUM = 25

#===================================================
# basic functions
#=============================================== ====

np.random.seed(SEED_in)


#---------------------------------------------------
def function( points_kn, params ):

#    print 'working on ', indx
    inv_cov, det_cov, M_j, U_iq = params

    # construct area fraction
    points_kq = np.c_[ points_kn, np.ones( len( points_kn ) ) ]
    

    # if the points do not form a triangle
    if np.linalg.det( points_kq ) == 0. :
        
        term = 0.

    else :

        # construct albedo
        X_albd_kj = np.dot( points_kn, V_nj ) + M_j

        # if albedo is not between 0 and 1, discard
        if ( np.any( X_albd_kj < 0. ) or np.any( X_albd_kj > 1. ) ) :

            term = 0.

        # if the data points are not enclosed by the three points, discard
        else :
 
            x_area_ik  = np.dot( U_iq, np.linalg.inv( points_kq ) )

            if ( np.any( x_area_ik < 0. ) ) :

                # print 'x_area_ik', x_area_ik
                # print 'points_kn', points_kn
                term = 0.

            else :

#                print '3rd gate passed'
                x_area_ave = np.average( x_area_ik, axis=0 )        
                x_area_std = np.std( x_area_ik, axis=0 )
                dx_area_ik = ( x_area_ik - x_area_ave )/x_area_std
                term1 = -0.5 * np.sum( np.diag( np.dot( np.dot( dx_area_ik.T, inv_cov ), dx_area_ik ) ) )
                term2 = -0.5 * np.log( det_cov )
                term  = np.exp( term1 + term2 )
#                print 'term1', term1
#                print 'term2', term2
#                print 'term' , term

    return term



#---------------------------------------------------
def multicore_function( indx, params ):

    print 'indx', indx
#    print 'working on ', indx
    points_valid_pn, inv_cov, det_cov, M_j, U_iq = params

    params2 = ( inv_cov, det_cov, M_j, U_iq )
    point1_n = points_valid_pn[indx]

    terms = 0.
    for p2 in xrange( len( points_valid_pn ) ):

        point2_n = points_valid_pn[p2]

        for p3 in xrange( len( points_valid_pn ) ):

            point3_n = points_valid_pn[p3]
            points_kn = np.vstack( [ point1_n, point2_n, point3_n ] )
            terms += function( points_kn, params2 )

    return terms


#--------------------------------------------------
def allowed_region( V_nj, ave_j ):

    # read PCs
    PC1 = V_nj[0]
    PC2 = V_nj[1]
    n_band = len( PC1 )
    band_ticks = np.arange( n_band )

    x_ticks = np.linspace(X_MIN,X_MAX,100)
    y_ticks = np.linspace(Y_MIN,Y_MAX,100)
    x_mesh, y_mesh, band_mesh = np.meshgrid( x_ticks, y_ticks, band_ticks, indexing='ij' )
    vec_mesh = x_mesh * PC1[ band_mesh ] + y_mesh * PC2[ band_mesh ] + ave_j[ band_mesh ]

    x_grid, y_grid = np.meshgrid( x_ticks, y_ticks, indexing='ij' )
    prohibited_grid = np.zeros_like( x_grid )

    for ii in xrange( len( x_ticks ) ) :
        for jj in xrange( len( y_ticks ) ) :

            if np.any( vec_mesh[ii][jj] < 0. ) :
                prohibited_grid[ii][jj] = 1
                if np.any( vec_mesh[ii][jj] > 1. ) :
                    prohibited_grid[ii][jj] = 3
            elif np.any( vec_mesh[ii][jj] > 1. ) :
                prohibited_grid[ii][jj] = 2
            else :
                prohibited_grid[ii][jj] = 0

    return x_grid, y_grid, prohibited_grid



#=============================================================================
def generate_cmap(colors):
    """
    copied from) http://qiita.com/kenmatsu4/items/fe8a2f1c34c8d5676df8
    """
    values = range(len(colors))
    vmax = np.ceil(np.max(values))
    color_list = []
    for v, c in zip(values, colors):
        color_list.append( ( v/ vmax, c) )
    return LinearSegmentedColormap.from_list('custom_cmap', color_list)



#=============================================================================
def call_multicore( list_index, args ):

    p = multiprocessing.Pool( N_CPU )
    result = p.map( functools.partial( multicore_function, params=args ), list_index )
    return result



#===================================================
if __name__ == "__main__":





    # Load input data
    Obs_ij = np.loadtxt( INFILE_DIR + INFILE )
    Time_i  = np.arange( len( Obs_ij ) ) / ( 1.0 * len( Obs_ij ) )
    n_band = len( Obs_ij.T )

    # PCA
    print 'Performing PCA...'
    n_pc, V_nj, U_in, M_j = PCA.do_PCA( Obs_ij, E_cutoff=1e-2, output=True )

    if not ( n_pc == N_TYPE - 1 ) :
        print 'ERROR: This code is only applicable for 3 surface types!'
        sys.exit()


    # flipping
    V_nj[0] = -1. * V_nj[0]
    U_in.T[0] = -1. * U_in.T[0]
#    V_nj[1] = -1. * V_nj[1]
#    U_in.T[1] = -1. * U_in.T[1]

    U_iq = np.c_[ U_in, np.ones( len( U_in ) ) ]

    l_dim   = len( Obs_ij )
    cov     = prior.get_cov( 1.0, 0.0, LAMBDA_CORR, l_dim, periodic=False )
    inv_cov = np.linalg.inv( cov )
    det_cov = np.linalg.det( cov )

#    print 'det_cov', det_cov
#    print 'inv_cov', inv_cov

    x_ticks = np.linspace( X_MIN, X_MAX, X_NUM )
    y_ticks = np.linspace( Y_MIN, Y_MAX, Y_NUM )

    xindx_ticks = np.arange( X_NUM )
    yindx_ticks = np.arange( Y_NUM )

    x_ticks_mesh, y_ticks_mesh = np.meshgrid( x_ticks, y_ticks, indexing='ij' )

    points_pn = np.c_[ x_ticks_mesh.flatten(), y_ticks_mesh.flatten() ]

    # construct albedo
    albd_pj = np.dot( points_pn, V_nj ) + M_j
    list_indx = np.where( np.all( 0 < albd_pj, axis=1 ) * np.all( albd_pj < 1, axis=1 ) )[0]

    points_valid_pn = points_pn[ list_indx ]

    print 'len(points_pn)', len(points_pn)
    print 'len(points_valid_pn)', len(points_valid_pn)

    now = datetime.datetime.now()
    print now.strftime("%Y-%m-%d %H:%M:%S")

    # multiprocessing
    params = ( points_valid_pn, inv_cov, det_cov, M_j, U_iq )
    list_index = np.arange( len( points_valid_pn ) )
    list_term_p = call_multicore( list_index, params )
    terms_p     = np.array( list_term_p )

    print terms_p
                
    now = datetime.datetime.now()
    print now.strftime("%Y-%m-%d %H:%M:%S")

    z_mesh = griddata( points_valid_pn, terms_p, points_pn, method='linear', fill_value=0. )

    z_mesh = z_mesh.reshape( x_ticks_mesh.shape )

    fig = plt.figure(figsize=(3, 6) )
    ax = fig.add_subplot( 111, aspect='equal' )

    ax.set_xlabel( 'PC 1' )
    ax.set_xlim([X_MIN, X_MAX])
    ax.set_ylabel( 'PC 2' )
    ax.set_ylim([Y_MIN, Y_MAX])

    cax  = ax.pcolor( x_ticks_mesh, y_ticks_mesh, z_mesh, cmap=cm.Greys )
    cbar = fig.colorbar( cax )

    #--------------------------------------------------------------------------
    # start from answer region
    # projection of 'answer' onto PC plane
    albd_answer_kj  = np.loadtxt( ALBDFILE ).T
    dalbd_answer_kj = albd_answer_kj - M_j
    coeff_kn        = np.dot( dalbd_answer_kj, V_nj.T )
    answer_x, answer_y = coeff_kn[:,0:2].T

    plt.scatter( answer_x[0], answer_y[0], marker='o', c='blue' )
    plt.scatter( answer_x[1], answer_y[1], marker='s', c='red' )
    plt.scatter( answer_x[2], answer_y[2], marker='^', c='green' )

    ax.plot( U_in.T[0], U_in.T[1], color='k', marker='.' )

#    x_grid, y_grid, prohibited_grid = allowed_region( V_nj, M_j )
#    mycm = generate_cmap(['white', 'gray'])
#    ax.pcolor( x_grid, y_grid, prohibited_grid, cmap=mycm )

    plt.savefig( 'tmp3.png', bbox_inches='tight' )
