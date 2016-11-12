import numpy as np
import sys
import corner
import datetime
import os

import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.colors import LinearSegmentedColormap

from fitlc_params import NUM_MCMC, NUM_MCMC_BURNIN, SEED_AMP, SIGMA_Y, NOISELEVEL, \
    REGULARIZATION, deg2rad, N_SIDE, INFILE, calculate_walkers, \
    ALBDFILE, AREAFILE, SLICE_TYPE, N_SLICE_LONGITUDE, GEOM

import prior
import reparameterize

import PCA
import shrinkwrap

import geometry

LOOP_MAX  = 10000
COUNT_MAX = 100
SEED_in  = 2013

SIGMA_Y = 100.
WL_AMP  = 0.
LAMBDA_CORR_DEG = 120
LAMBDA_CORR = LAMBDA_CORR_DEG * ( np.pi/180. )

RESOLUTION=1000
# RESOLUTION=100

# March 2008
#LAT_S = -0.5857506  # sub-solar latitude
#LON_S = 267.6066184  # sub-solar longitude
#LAT_O = 1.6808370  # sub-observer longitude
#LON_O = 210.1242232 # sub-observer longitude


#===================================================
# basic functions
#=============================================== ====

np.random.seed(SEED_in)


#---------------------------------------------------
def regularize_area_GP( x_area_lk, regparam ):

    sigma, wn_rel_amp_seed, lambda_angular = regparam

    wn_rel_amp = np.exp( wn_rel_amp_seed ) / ( 1. + np.exp( wn_rel_amp_seed ) )
#    print 'wn_rel_amp', wn_rel_amp
#    print 'lambda_angular', lambda_angular
    l_dim = len( x_area_lk )
    cov = prior.get_cov( sigma, wn_rel_amp, lambda_angular, l_dim )

#    print 'cov', cov
    inv_cov = np.linalg.inv( cov )
    det_cov = np.linalg.det( cov )
    if ( det_cov == 0. ):
        print 'det_cov', det_cov
        print 'cov', cov

#    print 'inv_cov', inv_cov
    x_area_ave = 1./len(x_area_lk.T)
    dx_area_lk = x_area_lk[:,:-1] - x_area_ave
    term1_all = np.dot( dx_area_lk.T, np.dot( inv_cov, dx_area_lk ) )
    term1 = -0.5 * np.sum( term1_all.diagonal() )
    term2 = -0.5 * np.log( det_cov )
#    print 'term1, term2', term1, term2

    prior_wn_rel_amp = np.log( wn_rel_amp / ( 1. + np.exp( wn_rel_amp_seed ) )**2 )

    return term1, term2, prior_wn_rel_amp

#---------------------------------------------------
def regularize_area_GP_new( x_area_lk, regparam ):

    sigma, wn_rel_amp, lambda_angular = regparam

#    print 'wn_rel_amp', wn_rel_amp
#    print 'lambda_angular', lambda_angular
    l_dim = len( x_area_lk )
    cov = prior.get_cov( sigma, wn_rel_amp, lambda_angular, l_dim )

#    print 'cov', cov
    inv_cov = np.linalg.inv( cov )
    det_cov = np.linalg.det( cov )
    if ( det_cov == 0. ):
        print 'det_cov', det_cov
        print 'cov', cov

#    print 'inv_cov', inv_cov
    x_area_ave = 1./len(x_area_lk.T)
    dx_area_lk = x_area_lk[:,:-1] - x_area_ave
    term1_all = np.dot( dx_area_lk.T, np.dot( inv_cov, dx_area_lk ) )
    term1 = -0.5 * np.sum( term1_all.diagonal() )
    term2 = -0.5 * np.log( det_cov )
#    print 'term1, term2', term1, term2

    return term1, term2

#--------------------------------------------------
def allowed_region( V_nj, ave_j ):

    # read PCs
    PC1 = V_nj[0]
    PC2 = V_nj[1]
    n_band = len( PC1 )
    band_ticks = np.arange( n_band )

    x_ticks = np.linspace(-0.4,0.2,RESOLUTION)
    y_ticks = np.linspace(-0.2,0.4,RESOLUTION)
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


#===================================================
if __name__ == "__main__":


    # Create directory for this run
    now = datetime.datetime.now()
    startstr = now.strftime("%Y-%m-%d--%H-%M")
    run_dir = "output/" + startstr + "/"
    os.mkdir(run_dir)
    print "Created directory:", run_dir

    # Save THIS file and the param file for reproducibility!
    thisfile = os.path.basename(__file__)
    paramfile = "fitlc_params.py"
    priorfile = "prior.py"
    newfile = run_dir + thisfile
    commandString1 = "cp " + thisfile + " " + newfile
    commandString2 = "cp "+paramfile+" " + run_dir+paramfile
    commandString3 = "cp "+priorfile+" " + run_dir+priorfile
    os.system(commandString1)
    os.system(commandString2)
    os.system(commandString3)
    print "Saved :", thisfile, " &", paramfile

    # Load input data
    Obs_ij = np.loadtxt(INFILE)
    Obsnoise_ij = ( NOISELEVEL * Obs_ij )
    Time_i  = np.arange( len( Obs_ij ) ) / ( 1.0 * len( Obs_ij ) )
    n_band = len( Obs_ij.T )

    # Initialization of Kernel
    if SLICE_TYPE == 'time' :
        print 'Decomposition into time slices...'
        n_slice = len( Time_i )
        Kernel_il = np.identity( n_slice )

    elif SLICE_TYPE == 'longitude' :
        print 'Decomposition into longitudinal slices...'
        n_slice = N_SLICE_LONGITUDE
        # (Time_i, n_slice, n_side, param_geometry):
        Kernel_il = geometry.kernel( Time_i, n_slice, N_SIDE, GEOM )

    else : 
        print '\nERROR : Unknown slice type\n'
        sys.exit()

    # PCA
    print 'Performing PCA...'
    n_pc, V_nj, U_in, M_j = PCA.do_PCA( Obs_ij, run_dir, E_cutoff=1e-2 )
    n_type = n_pc + 1
    if n_type != 3 :
        print 'ERROR: This code is only applicable for 3 surface types!'
        sys.exit()

    # shrinkwrap
    print 'Perfoming shrink-wrapping...'
    # N ( = n_PC ): number of principle components
    # M ( = n_PC + 1 ) : number of vertices
    A_mn, P_im   = shrinkwrap.do_shrinkwrap( U_in, n_pc, run_dir )
    X0_albd_kj   = np.dot( A_mn, V_nj )
    X0_albd_kj   = X0_albd_kj + M_j
    if ( SLICE_TYPE=='time' ) :
        X0_area_lk   = P_im
    else :
        X0_area_lk = np.ones( n_slice*n_type ).reshape([n_slice, n_type])/(n_type*1.0)

    # Save initial condutions
    np.savetxt( run_dir+'X0_albd_jk', X0_albd_kj.T )
    np.savetxt( run_dir+'X0_area_lk', X0_area_lk )

    U_iq = np.c_[ U_in, np.ones( len( U_in ) ) ]

    PC1_limit = [-0.4, 0.2] # manually set for now
    PC2_limit = [-0.1, 0.4] # manually set for now

    points_kn_list     = []
    X_area_ik_list     = []
    X_albd_kj_list     = []
    chi2_list          = []
    ln_prior_area_list = []
    ln_prior_albd_list = []
    regterm1_list      = []
    regterm2_list      = []


    count = 0
    for loop in xrange( LOOP_MAX ):

        # generate three random points in PC plane ( 3 vertices x 2 PCs )
        points_PC1 = np.random.uniform( PC1_limit[0], PC1_limit[1], 3 )
        points_PC2 = np.random.uniform( PC2_limit[0], PC2_limit[1], 3 )

        points_kn = np.c_[ points_PC1, points_PC2 ]

        # reconstruct albedo
        X_albd_kj = np.dot( points_kn, V_nj ) + M_j

        # if albedo is not between 0 and 1, discard
        # otherwise, proceed
        if not( np.any( X_albd_kj < 0. ) or np.any( X_albd_kj > 1. ) ):

            # construct area fraction
            points_kq = np.c_[ points_kn, np.ones( len( points_kn ) ) ]
            X_area_ik  = np.dot( U_iq, np.linalg.inv( points_kq ) )

            # If area is not within 0 and 1, discard
            # otherwise, proceed
            if not( np.any( X_area_ik < 0. ) or np.any( X_area_ik > 1. ) ):

                points_kn_list.append( points_kn )
                X_area_ik_list.append( X_area_ik )
                X_albd_kj_list.append( X_albd_kj )

                # chi^2
                Obs_estimate_ij = np.dot( X_area_ik , X_albd_kj )
                chi2 = np.sum( ( Obs_ij - Obs_estimate_ij )**2 )
                chi2_list.append( chi2 )
                
                Y_array = reparameterize.transform_X2Y(X_albd_kj, X_area_ik)

                # flat prior for area fraction
                Y_area_ik = Y_array[n_type*n_band:].reshape([n_slice, n_type-1])
                ln_prior_area = prior.get_ln_prior_area_new( Y_area_ik )
                ln_prior_area_list.append( ln_prior_area )

                # log prior for albedo
                Y_albd_kj = Y_array[0:n_type*n_band].reshape([n_type, n_band])
                ln_prior_albd = prior.get_ln_prior_albd( Y_albd_kj )
                ln_prior_albd_list.append( ln_prior_albd )

                # regularization ?
                regparam     = ( SIGMA_Y, WL_AMP, LAMBDA_CORR )
                term1, term2 = regularize_area_GP_new( X_area_ik, regparam )
                regterm1_list.append( term1 )
                regterm2_list.append( term2 )

                count = count + 1
                print 'count', count

                if count > COUNT_MAX :
                    break

        loop = loop + 1

    # loop end

    # spider graph (?)
    ax1 = plt.subplot(adjustable='box', aspect=1.0)
    ax1.set_xlim([-0.4,0.2])
    ax1.set_ylim([-0.2,0.4])
    ax1.set_xticks([ -0.4, -0.2, 0.0, 0.2 ])
    ax1.set_yticks([ -0.2, 0.0, 0.2, 0.4 ])

    print 'np.array( regterm1_list )', np.array( regterm1_list )
    print 'np.array( regterm2_list )', np.array( regterm2_list )

    colorterm = np.array( regterm1_list ) + np.array( regterm2_list )
    print 'colorterm', colorterm
    colorrange = ( np.max( colorterm ) - np.min( colorterm ) ) * 1.5
    colorlevel = ( colorterm - np.min( colorterm ) ) / colorrange

    colorlevel_sorted = colorlevel[np.argsort( colorlevel )][::-1]
    points_kn_array = np.array( points_kn_list )
    points_kn_array_sorted  = points_kn_array[np.argsort( colorlevel )][::-1]
    for ii in xrange( count ) :
        points_kn = points_kn_array_sorted[ii]
        points_kn = np.vstack( [ points_kn, points_kn[0] ] )
        plt.plot( points_kn.T[0], points_kn.T[1], color=cm.hot(colorlevel_sorted[ii]) )


    # allowed region
    x_grid, y_grid, prohibited_grid = allowed_region( V_nj, M_j )
    print 'prohibited_grid.shape', prohibited_grid.shape
    cm = generate_cmap(['white', 'gray'])
    plt.pcolor( x_grid, y_grid, prohibited_grid, cmap=cm )

    # data
    plt.plot( U_in.T[0], U_in.T[1], 'k' )
    plt.plot( U_in.T[0], U_in.T[1], marker='.', c="black", label='data' )

    plt.savefig( INFILE+'_PCplane.pdf' )