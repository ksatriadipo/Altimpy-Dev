"""
Module with functions to construct and process time series. 

"""
# Fernando Paolo <fpaolo@ucsd.edu>
# August 6, 2013 

import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import detrend
from random import shuffle
from altimpy.const import *
from altimpy.util import *

from sklearn.linear_model import LassoCV
'''
try:
    from sklearn.preprocessing import PolynomialFeatures
except:
    raise, 'need scikit-learn version <= 0.15'
'''

# DEPRECATED. Use sklearn instead
from patsy import dmatrix

#----------------------------------------------------------------
# Backscatter corrections
#----------------------------------------------------------------

def backscatter_corr(H, G, diff=False, robust=False, plot=False):
    """Apply the backscatter correction to an elevation-change time series.

    It uses constant correlation and sensitivity (transfer function).

    Implements the correction using a time series of dAGC (or dsigma) formed
    exactly as the dh time series, following: Zwally, et al. (2005); Yi, et
    al. (2011):
        
        H_cor(t) = H(t) - S * G(t) - H0

    where H(t) = dh(t0,t), G(t) = dAGC(t0,t) and S = dH/dG = const.

    Parameters
    ----------
    H : array-like
        Time series of elevation change (m).
    G : array-like
        Time series of backscatter change, AGC or sigma0 (dB).
    diff : boolean, default False
        If False, derive mix-term sensitivity as dH/dG; if True, derive
        short-term sensitivity using the derivatives (i.e., differenced series)
        dH'/dG'.
    robust : boolean, default False
        Performs linear fit by robust regression (M-estimate), otherwise uses
        Ordinary Least Squares (default).
    plot : boolean, default False
        Plots the backscatter-elevation correlation.

    Returns
    -------
    H_cor : array-like
        Corrected elevation-change series.
    R : float
        Correlation coeficient.
    S : float
        Sensitivity factor (transfer function).

    Notes
    -----
    S is slope of linear fit to correlation(dG|dG', dH|dH')
    H0 is intercept of linear fit to correlation(dG|dG', dH|dH')

    It excludes the NaNs forming continuous series to differentiate and
    calculate the correlations.

    Time series must have at least 4 values (3 differences) to fit a line.
    Otherwise, does not applies correction.

    See also
    --------
    backscatter_corr2, bacscatter_corr3

    """
    # use only non-null entries for correlations
    ind, = np.where(~np.isnan(H) & ~np.isnan(G))
    H2, G2 = H[ind], G[ind]
    if len(H2) < 4:
        return [H, np.nan, np.nan]

    if diff:
        # diff -> N-1
        if isinstance(H2, pd.Series):
            H2, G2 = np.diff(H2.values), np.diff(G2.values)
        else:
            H2, G2 = np.diff(H2), np.diff(G2)
    else:
        pass

    # correlation coef
    R = np.corrcoef(G2, H2)[0,1]

    # correlation grad and intercept
    if robust:
        S, H0 = linear_fit_robust(G2, H2, return_coef=True)
    else:
        S, H0 = linear_fit(G2, H2, return_coef=True)

    if plot:
        plt.plot(G2, S*G2+H0, 'k')
        plt.plot(G2, H2, 'ob')
        plt.title('r = %.2f   s = %.2f   Ho = %.2f' % (R, S, H0))
        plt.show()

    # a) no correction applied if |R| < 0.2
    # b) fix values outside the range [-0.2, 0.7]
    if np.abs(R) < 0.2:                          
        S = 0.0
        H0 = 0.0
    elif S < -0.2:
        S = -0.2
    elif S > 0.7:
        S = 0.7
    else:
        pass

    '''
    G0 = -H0 * S**(-1)
    H_cor = H - S * (G - G0)
    '''
    H_cor = H - S * G - H0  # this is equivalent to the 2 lines above!

    return [H_cor, R, S]


def backscatter_corr2(H, G, diff=False, robust=False, npts=9, centered=False,
                      plot=False):
    """Apply the backscatter correction to an elevation-change time series.

    It uses time-variable correlation and sensitivity (transfer function).

    Implements the correction using a time series of dAGC formed exactly as the
    dh time series. Calculates correlations and sensitivities on time windows 
    for each point, following khvorostovsky (2011):
        
        H_cor(t) = H(t) - S(t) * G(t) - H0(t)

    where H(t) = dh(t0,t), G(t) = dAGC(t0,t) and S(t) = dH/dG(t).
 
    Parameters
    ----------
    H : array-like
        Time series of elevation change (m).
    G : array-like
        Time series of backscatter change, AGC or sigma0 (dB).
    diff : boolean, default False
        If False, derive mix-term sensitivity as dH/dG; if True, derive
        short-term sensitivity using the derivatives (i.e., differenced series)
        dH'/dG'.
    robust : boolean, default False
        Performs linear fit by robust regression (M-estimate), otherwise uses
        Ordinary Least Squares (default).
    npts : int, optional
        Number of points used for correlation at each time (window size).
    centered : boolean, default False
        It centers the correlation window on each point, othewise the point of
        calculation is at the begening of the window.
    plot : boolean, default False
        Plots the backscatter-elevation correlation.

    Returns
    -------
    H_cor : array-like
        Corrected elevation-change series.
    RR : array-like
        Correlation coeficient for each point.
    SS : array-like
        Sensitivity factor for each point (transfer function).

    Notes
    -----
    S is slope of linear fit to correlation(dG|dG', dH|dH')
    H0 is intercept of linear fit to correlation(dG|dG', dH|dH')
    RR, SS, HH are time series of the respective parameters.

    It excludes the NaNs forming continuous series to differentiate and
    calculate the correlations.

    See also
    --------
    backscatter_corr, bacscatter_corr3

    """
    if np.alltrue(np.isnan(H)):
        return [H, np.nan, np.nan]

    H = referenced(H, to='first')
    G = referenced(G, to='first')

    N = len(H)
    RR = np.empty(N, 'f8') * np.nan
    SS = np.empty(N, 'f8') * np.nan
    HH = np.empty(N, 'f8') * np.nan
    if centered:
        l = int(npts/2.)
        N2 = N
    else:
        l = npts
        N2 = N-l

    for k in range(N2):
        if centered and (k < l or k >= N-l): 
            continue
        # take chunks (time window) every iteration
        if centered:
            H2, G2 = H[k-l:k+l+1], G[k-l:k+l+1]    
        else:
            H2, G2 = H[k:k+l+1], G[k:k+l+1]    
        ind, = np.where((~np.isnan(H2)) & (~np.isnan(G2)))
        H2, G2 = H2[ind], G2[ind]
        if diff:
            # diff -> N-1
            if isinstance(H2, pd.Series):
                H2, G2 = np.diff(H2.values), np.diff(G2.values)
            else:
                H2, G2 = np.diff(H2), np.diff(G2)
        else:
            pass

        # correlation coef
        R = np.corrcoef(G2, H2)[0,1]

        # correlation grad and intercept
        if robust:
            S, H0 = linear_fit_robust(G2, H2, return_coef=True)
        else:
            S, H0 = linear_fit(G2, H2, return_coef=True)

        RR[k] = R
        SS[k] = S
        HH[k] = H0 

        if plot:
            plt.plot(G2, S*G2+H0, 'k')
            plt.plot(G2, H2, 'ob')
            plt.title('r = %.2f   s = %.2f   Ho = %.2f' % (R, S, H0))
            plt.show()

    # fill both ends
    if centered:
        RR[:l] = RR[l]
        SS[:l] = SS[l]
        HH[:l] = HH[l]
    RR[N-l:] = RR[N-l-1]
    SS[N-l:] = SS[N-l-1]
    HH[N-l:] = HH[N-l-1]

    # a) no correction applied if |R| < 0.2
    # b) fix values outside the range [-0.2, 0.7]
    ii, = np.where(np.abs(RR) < 0.2)
    SS[ii] = 0.0
    HH[ii] = 0.0
    SS[SS<-0.2] = -0.2
    SS[SS>0.7] = 0.7

    # fill with NaN when no data in dh TS
    jj, = np.where(np.isnan(H))
    RR[jj] = np.nan
    SS[jj] = np.nan
    HH[jj] = np.nan

    '''
    GG = -HH * SS**(-1)  # ambiguity when S = 0!
    H_cor = H - SS * (G - GG)
    '''
    H_cor = H - SS * G - HH  # this is equivalent to the 2 lines above!

    return [H_cor, RR, SS]


# DEPRECATED! Needs revision.
def backscatter_corr3(H, G, t, intervals, diff=False, robust=False, 
                      max_increase=None):
    """Apply the backscatter correction to an elevation-change time series.

    It uses interval-variable correlation and sensitivity (transfer function).

    Implements the correction using a time series of dAGC formed exactly as the
    dh time series. Calculates correlations and sensitivities on given time
    intervals:

        dh_cor(t) = dh(t) - s(intv) * dg(t) - h0(intv)

    where dh(t) = dh(t0,t), dg(t) = dAGC(t0,t) and s(intv) = dh/dg[intv].
 
    Parameters
    ----------
    H : array-like
        Time series of elevation change (m).
    G : array-like
        Time series of backscatter change, AGC or sigma0 (dB).
    t : datetime
        Times in datetime objects.
    intervals : list 
        List with datetime tuples defining the time intervals: [(dt1,dt2), 
        (dt2,dt3), ...].
    diff : boolean, default False
        If False, derive mix-term sensitivity as dH/dG; if True, derive
        short-term sensitivity using the derivatives (i.e., differenced series)
        dH'/dG'.
    robust : boolean, default False
        Performs linear fit by robust regression (M-estimate), otherwise uses
        Ordinary Least Squares (default).
    max_increase : int, optional
        Only apply correction if the amplitude of "corrected" data is not 
        greater than 'max_increase' times the original value.

    Returns
    -------
    H_cor : array-like
        Corrected elevation-change series.
    RR : array-like
        Correlation coeficient for each point.
    SS : array-like
        Sensitivity factor for each point (transfer function).

    Notes
    -----
    S is slope of linear fit to correlation(dG|dG', dH|dH')
    H0 is intercept of linear fit to correlation(dG|dG', dH|dH')
    RR, SS, HH are time series of the respective parameters.

    See also
    --------
    backscatter_corr, backscatter_corr2

    """
    if np.alltrue(np.isnan(H)):
        return [H, np.nan, np.nan]

    H = referenced(H, to='first')
    G = referenced(G, to='first')

    N = len(H)
    RR = np.empty(N, 'f8') * np.nan
    SS = np.empty(N, 'f8') * np.nan
    HH = np.empty(N, 'f8') * np.nan

    # take chunks (time intervals) at every iteration
    for tt in intervals:
        kk, = np.where((t >= tt[0]) & (t < tt[1]))
        H2, G2 = H[kk], G[kk]
        ind, = np.where((~np.isnan(H2)) & (~np.isnan(G2)))
        H2, G2 = H2[ind], G2[ind]
        if diff:
            if isinstance(H2, pd.Series):
                # pandas diff -> N (w/NaN)
                H2, G2 = H2.diff(), G2.diff()
                H2, G2 = H2[H2.notnull()], G2[G2.notnull()]
            else:
                # numpy diff -> N-1
                H2, G2 = np.diff(H2), np.diff(G2)
        else:
            pass

        # correlation coef
        R = np.corrcoef(G2, H2)[0,1]

        # correlation grad and intercept
        if robust:
            S, H0 = linear_fit_robust(G2, H2, return_coef=True)
        else:
            S, H0 = linear_fit(G2, H2, return_coef=True)

        RR[kk] = R
        SS[kk] = S
        HH[kk] = H0 

    # a) no correction applied if |R| < 0.2
    # b) fix values outside the range [-0.2, 0.7]
    ii, = np.where(np.abs(RR) < 0.2)
    SS[ii] = 0.0
    HH[ii] = 0.0
    SS[SS<-0.2] = -0.2
    SS[SS>0.7] = 0.7

    # fill with NaN when no data in dh TS
    jj, = np.where(np.isnan(H))
    RR[jj] = np.nan
    SS[jj] = np.nan
    HH[jj] = np.nan

    H_cor = H - SS * G - HH
    '''
    if max_increase is not None:
        # apply correction only if increase is not greater than p%
        H_cor = limit_correction(H, H_cor, max_increase=max_increase)
    '''
    #H_cor = referenced(H_cor, to='first')

    return [H_cor, RR, SS]

#----------------------------------------------------------------
# averaging time series
#----------------------------------------------------------------

def select_ref(df, dynamic=True):
    """Select the reference (column) time series."""
    if dynamic:
        # use column with max non-null entries as reference
        col = df.count().argmax()
    else:
        # use first column with non-null entries as reference
        for col, ts in df.iteritems():
            if ts.notnull().any(): break
    return col, df[col]


def select_ref_row(mat, dynamic=True):
    """Select the row with [max] non-null entries of a matrix."""
    if dynamic:
        # get index of row with max non-null entries 
        i_ref = np.argmax([np.count_nonzero(~np.isnan(row)) for row in mat])
    else:
        # get index of first row with non-null entries
        i_ref = np.nonzero([np.count_nonzero(~np.isnan(row)) for row in mat])[0].min()
    return i_ref


def reference_ts_matrix(data, i_ref):
    """Reference all rows with respect to the reference row."""
    nrow, ncols = data.shape
    row_ref = data[i_ref]
    for i in xrange(data.shape[0]):
        row = data[i]
        if i != i_ref and not np.isnan(row).all():
            idx = np.where(~np.isnan(row) & ~np.isnan(row_ref))[0][0] # first elem
            offset = row[idx] - row_ref[idx]
            data[i] -= offset
            #print i, idx, offset
    return data


def find_non_overlap(df, col_ref):
    """Find the columns with < 2 overlapping values to the reference."""
    ts_ref = df[col_ref].values
    cols = []
    for c, ts in df.iteritems():
        if c == col_ref: continue  # skip the ref column !!!
        #ind, = np.where(ts_ref.notnull() & ts.notnull())
        ind, = np.where(~np.isnan(ts_ref) & ~np.isnan(ts))
        if len(ind) < 2:
            cols.append(c)
    return cols


def ref_by_offset(df, col_ref):
    """
    Reference all time series to a common reference.

    Computes the 'offset' of the selected reference time series to each
    other time series (Paolo et al.).

    The selected reference time series can be:
    - the one with the first reference time (first non-null time series)
    - the one with the maximum non-null entries (dynamic referencing)

    Parameters
    ----------
    df : DataFrame
        Pandas DataFrame containing all multi-reference time series, i.e.,
        the matrix representation of all forward [and backward] combinations.
    col_ref : key
        The column to be used as the reference time series.

    See also
    --------
    ref_by_first
    prop_err_by_first
    prop_err_by_offset
    prop_obs_by_offset
    prop_obs_by_first

    """
    ts_ref = df[col_ref].values
    for c, ts in df.iteritems():
        # find the non-null overlapping values
        ind, = np.where(~np.isnan(ts_ref) & ~np.isnan(ts))
        if len(ind) == 0: continue
        # compute offset with respect to the reference, and add the
        # 'offset' to entire ts (column)
        offset = np.mean(ts_ref - ts.values)  
        df[c] += offset


def ref_by_first(df, col_ref):
    """
    Reference all time series to a common reference.

    Computes the 'offset' of each element in the reference time series to the
    first non-zero element in each other time series (Davis et al.).

    Parameters
    ----------
    df : DataFrame
        Pandas DataFrame containing all multi-reference time series, i.e.,
        the matrix representation of all forward [and backward] combinations.
    col_ref : key
        The column to be used as the reference time series.

    See also
    --------
    ref_by_offset
    prop_err_by_offset
    prop_err_by_first
    prop_obs_by_offset
    prop_obs_by_first

    """
    ts_ref = df[col_ref].values
    for c, hi in zip(df.columns, ts_ref):
        # if not the ref column add the element 'hi' to entire ts (column)
        if c != col_ref:
            df[c] += hi


def prop_err_by_offset(df, col_ref):
    """
    Propagate the error due to the referencing procedure.

    The error propagation takes into account (1) the average of the differences to
    calculate the offset (e_offset), and (2) the addition of this offset to each
    element in the time series being referenced.

    For each time series there is one 'offset' and, consequently, one 'e_offset'
    associated to it.

    Parameters
    ----------
    df : DataFrame
        Pandas DataFrame containing all multi-reference time series, i.e.,
        the matrix representation of all forward [and backward] combinations.
    col_ref : key
        The column to be used as the reference time series.

    Notes
    -----
    reference one ts to another:
        x(t) = x1, x2, ..., xn
        y(t) = y1, y2, ..., yn
    error for differences: 
        d1 = x1 - y1 
        e_d1 = sqrt(e_x1**2 + e_y1**2)
    error for offset: 
        D = (d1 + d2 + ... + dn) / n
        e_D = sqrt(e_d1**2 + e_d2**2 + ... + e_dn**2) / n
            = sqrt(e_x1**2 + e_y1**2 + ... + e_xn**2 + e_yn**2) / n
    error for referenced h:
        h1' = h1 + D
        e_h1' = sqrt(e_h1**2 + e_D**2)

    See also
    --------
    ref_by_offset
    ref_by_first
    prop_err_by_first
    prop_obs_by_offset
    prop_obs_by_first

    """
    ts_ref = df[col_ref].values
    for c, ts in df.iteritems():
        if c == col_ref: continue  # skip the ref column!!!
        # find the non-null overlapping values
        ind, = np.where(~np.isnan(ts_ref) & ~np.isnan(ts))
        if len(ind) == 0: continue
        # sum in quadrature, calculate offset error and propagate
        e2_ref_sum = np.sum(ts_ref[ind].values**2)  # e**2 = variance
        e2_ts_sum = np.sum(ts[ind].values**2)
        e_offset = np.sqrt(e2_ref_sum + e2_ts_sum) / len(ind)
        df[c] = np.sqrt(ts.values**2 + e_offset**2) # add to each element


def prop_err_by_first(df, col_ref):
    """
    Propagate the error due to the referencing procedure.

    Parameters
    ----------
    df : DataFrame
        Pandas DataFrame containing all multi-reference time series, i.e.,
        the matrix representation of all forward [and backward] combinations.
    col_ref : key
        The column to be used as the reference time series.

    Notes
    -----
    reference one ts to another:
        x(t) = x1, x2, ..., xn
        y(t) = y1, y2, ..., yn
    error for differences: 
        d1 = x1 - y1 
        e_d1 = sqrt(e_x1**2 + e_y1**2)
    error for offset: 
        D = (d1 + d2 + ... + dn) / n
        e_D = sqrt(e_d1**2 + e_d2**2 + ... + e_dn**2) / n
            = sqrt(e_x1**2 + e_y1**2 + ... + e_xn**2 + e_yn**2) / n
    error for referenced h:
        h1' = h1 + D
        e_h1' = sqrt(e_h1**2 + e_D**2)

    See also
    --------
    ref_by_offset
    ref_by_first
    prop_err_by_first
    prop_obs_by_offset
    prop_obs_by_first

    """
    error_ref = df[col_ref][1:].values      # all elems but first one
    cols = df.columns[df.columns!=col_ref]  # all TS but TS_ref
    for c, e in zip(cols, error_ref):
        try:
            df[c] = np.sqrt(e**2 + df[c].values**2)
        except:
            pass

def prop_obs_by_offset(df, col_ref):
    """
    Propagate the number of observations due to the referencing procedure.

    The #obs propagation takes into account (1) the average of the differences to
    calculate the offset (n_offset), and (2) the addition of this offset to each
    element in the time series being referenced.

    For each time series there is one 'offset' and, consequently, one 'n_offset'
    associated to it.

    Parameters
    ----------
    df : DataFrame
        Pandas DataFrame containing all multi-reference time series, i.e.,
        the matrix representation of all forward [and backward] combinations.
    col_ref : key
        The column to be used as the reference time series.

    Notes
    -----
    1) #obs per difference = average *pairs* of obs between the 'ref' and 'ts'
    2) #obs per offset = average of #obs per difference
    3) #obs per referenced value = #obs value + #obs offset

    See also
    --------
    ref_by_offset
    ref_by_first
    prop_err_by_first
    prop_err_by_offset
    prop_obs_by_first

    """
    ts_ref = df[col_ref].values
    for c, ts in df.iteritems():
        if c == col_ref: continue  # skip the ref column!!!
        # find the non-null overlapping values
        ind, = np.where(~np.isnan(ts_ref) & ~np.isnan(ts))
        if len(ind) == 0: continue
        # obs per difference = average pairs of obs between 'ref' and 'ts'
        n_diff = (ts_ref[ind] + ts[ind]) / 2.
        # obs per offset = average of number of obs per difference
        n_offset = np.sum(n_diff) / len(ind)
        df[c] += round(n_offset)


def prop_obs_by_first(df, col_ref):
    """
    Propagate the number of observations due to the referencing procedure.

    The #obs propagation takes into account (1) the average of the differences to
    calculate the offset (n_offset), and (2) the addition of this offset to each
    element in the time series being referenced.

    For each time series there is one 'offset' and, consequently, one 'n_offset'
    associated to it.

    Parameters
    ----------
    df : DataFrame
        Pandas DataFrame containing all multi-reference time series, i.e.,
        the matrix representation of all forward [and backward] combinations.
    col_ref : key
        The column to be used as the reference time series.

    Notes
    -----
    1) #obs per difference = average *pairs* of obs between the 'ref' and 'ts'
    2) #obs per offset = average of #obs per difference
    3) #obs per referenced value = #obs value + #obs offset

    See also
    --------
    ref_by_offset
    ref_by_first
    prop_err_by_first
    prop_err_by_offset
    prop_obs_by_first

    """
    obs_ref = df[col_ref][1:].values        # all elems but first one
    cols = df.columns[df.columns!=col_ref]  # all TS but TS_ref
    for c, n in zip(cols, obs_ref):
        df[c] += n                      # don't like this way of C.Davis !!!


def weighted_average(df, df_nobs):
    """
    Calculate the unbiased weighted average time series, weighted by the
    number of observations.

    wi = ni / (n1 + n2 + ...)
    mean = w1 * h1 + w2 * h2 + ...

    """
    if np.alltrue(df.isnull()):
        ts_mean = df.sum(axis=1)           # if nothing, colapse matrix -> series
    else:
        # weights for averaging
        df_nobs[df_nobs==0] = 1            # to ensure dh=0 (n_obs=0) enters the average
        nobs_j = df_nobs.sum(axis=1)       # total #obs per row (col in matrix)
        w_ij = df_nobs.div(nobs_j, axis=0) # one weight per element (sum_col==1)
        ts_mean = (w_ij * df).sum(axis=1)  # weighted sum
        #print 'weight/col:', w_ij.sum(axis=1)
    return ts_mean


def weighted_average_error(df, df_nobs):
    """
    Calculate the unbiased weighted average time series for the standard error,
    weighted by the number of observations.

    se_mean = sqrt(w1**2 * se1**2 + w2**2 * se2**2 + ...)

    """
    if np.alltrue(np.isnan(df.values.astype(float))):  # astype is needed (bug in pandas)!!!
        ts_mean = df.sum(axis=1)           # if nothing, colapse matrix -> series
    else:
        # weights for averaging
        df_nobs[df_nobs==0] = 1            # to ensure dh=0 (n_obs=0) enters the average
        nobs_j = df_nobs.sum(axis=1)       # total #obs per row (col in matrix)
        w_ij = df_nobs.div(nobs_j, axis=0) # one weight per element (sum_col==1)
        ts_mean = np.sqrt((w_ij**2 * df**2).sum(axis=1)) 
    return ts_mean


#----------------------------------------------------------------
# Other functionalities
#----------------------------------------------------------------

def area_weighted_mean(X, area):
    """Compute the area-weighted-average time series from a 3d array.
    
    For each value in the average time series also returns the fraction
    of area covered by each average.

    Parameters
    ----------
    X : 3d-array 
        Array containing one time series per grid-cell, where the
        first dimension (i) is the time, and the second and thrid 
        dimensions (j and k) are the spatial coordinates (x,y).
    area : 2d-array
        A grid containing the area of each grid-cell on X, i.e.,
        the spatial coordinates.

    Returns
    -------
    ts : 1d-array
        The average time series weighted by each grid-cell area.
    ar : 1d-array
        The fraction of area covered by each average.

    Notes
    -----
    This function uses numpy 'masked arrays'.

    See also
    --------
    get_area_cells
    area_weighted_mean_err

    """
    nt, _, _ = X.shape
    X = np.ma.masked_invalid(X)
    total_area = float(X.sum(axis=0).count())
    ts = np.zeros(nt, 'f8')  # container for output avrg time series
    ar = np.zeros(nt, 'f8')  # container for fraction of area covered
    for k in range(nt):      # weight-average each 2d time step
        G = X[k,...]
        W = area.copy()
        W[np.isnan(G)] = 0
        s = W.sum()
        if s != 0:
            W /= s           # normalize such that sum(W) == 1
        else:
            W[:] = 0 
        ts[k] = np.sum(W*G)  # area-weighted average per time step
        ar[k] =  G.count() / total_area
    return [ts, ar]


def area_weighted_mean_err(X, area):
    """Propagate the error for the area-weighted-mean from a 3d array.
    
    Parameters
    ----------
    X : 3d-array 
        Array containing one time series per grid-cell, where the
        first dimension (i) is the time, and the second and thrid 
        dimensions (j and k) are the spatial coordinates (x,y).
    area : 2d-array
        A grid containing the area of each grid-cell on X (the spatial
        coordinates).

    Returns
    -------
    ts : 1d-array
        The average time series weighted by each grid-cell area.

    Notes
    -----
    This function uses numpy 'masked arrays'.

    See also
    --------
    get_area_cells
    area_weighted_mean

    """
    nt, _, _ = X.shape
    X = np.ma.masked_invalid(X)
    total_area = float(X.sum(axis=0).count())
    ts = np.zeros(nt, 'f8')  # container for output avrg time series
    for k in range(nt):      # weight-average each 2d time step
        G = X[k,...]
        W = area.copy()
        W[np.isnan(G)] = 0
        s = W.sum()
        if s != 0:
            W /= s           # normalize such that sum(W) == 1
        else:
            W[:] = 0 
        ts[k] = np.sqrt(np.sum(W**2 * G**2))  # error per time step 
    return ts


def kfold(X, K, randomise=False):
    """Generates K training/testing pairs from the indices of X.
    
    Each pair is a partition of the indices in X [0,..,N-1], where testing is
    an iterable of length len(X)/K. So each training iterable is of length
    (K-1)*len(X)/K.
    
    If randomise is true, the indices of X are shuffled before partitioning,
    otherwise the order is preserved in training and testing.

    """
    ind = xrange(len(X))
    if randomise: 
        ind = list(ind)
        shuffle(ind)
    for k in xrange(K):
    	i_training = [i for i in ind if i % K != k]
    	i_testing = [i for i in ind if i % K == k]
    	yield i_training, i_testing


def polyfit_kfold(x, y, k=10, deg=2, weight=None, randomise=False):
    """Perform polyfit on k-fold train data and evaluate on test data.

    Return the average MSE.
    See 'lstsq_cv'.
    """
    mse_ = [] 
    w_train = None
    for i_train, i_test in kfold(x, k, randomise=randomise):
        if weight is not None:
            w_train = weight[i_train]
        p = np.polyfit(x[i_train], y[i_train], deg, w=w_train)
        y_pred = np.polyval(p, x[i_test])
        y_true = y[i_test]
        mse_ = np.append(mse_, mse(y_true, y_pred))
    return np.mean(mse_)


# TODO: extend the way degrees are passed, e.g., (0,3) and [0, 1, 2, 3]
def polyfit_select(x, y, cv=10, max_deg=3, weight=None, randomise=False):
    """Select best polynomial model using cross-validation.
    
    Return the order of selected model and each model MSE.

    See 'lstsq_cv'.

    """
    model_order = np.arange(1,max_deg+1)
    model_mse = np.zeros(len(model_order), 'f8')
    for i, n in enumerate(model_order):
        model_mse[i] = polyfit_kfold(x, y, k=cv, deg=n, weight=weight,
                                     randomise=randomise)
    return model_order[model_mse.argmin()], model_mse


def lstsq_cv(x, y, cv=10, x_pred=None, max_deg=3, weight=None, randomise=False,
               return_coef=False):
    """Least squares polynomial fit with cross-validation.

    The order of the polynomial is selected by k-fold CV.

    Supports NaNs.

    Parameters
    ----------
    x, y : feature and target, 1d arrays.
    cv : number of folds in the cross-validation.
    max_deg : maximum degree for testing polynomials.
    weight : weights for the least squares fit.
    randomise : randomises the data prior applying k-fold CV.
    return_coef : it returns extra parameters (see below).
    
    Returns
    -------
    y_pred : fitted polynomial evaluated on x.

    If 'return_coef=True', also returns:

    coef : coefficients of fitted polynomial.
    deg : degree of fitted polynomial.
    mse : average MSE across folds (tested polynomials).
    cov : covariance estimates of fitted coefficients.

    """
    ind, = np.where((~np.isnan(x)) & (~np.isnan(y)))
    x_, y_ = x[ind], y[ind]
    weight_ = None
    if x_pred is None:
        x_pred = x
    if weight is not None:
        weight_ = weight[ind]
    deg, mse = polyfit_select(x_, y_, cv=cv, max_deg=max_deg, weight=weight_,
                              randomise=randomise)
    coef, cov = np.polyfit(x_, y_, deg, w=weight_, cov=True)
    y_pred = np.polyval(coef, x_pred)  # predict on full data
    out = y_pred
    if return_coef:
        out = [y_pred, coef, deg, mse, cov]
    return out


def lasso_cv(x, y, x_pred=None, max_deg=3, cv=10, max_iter=1e3, return_model=False):
    """LASSO polynomial fit with cross-validation.
    
    Regularized polynomial regression (by penalized least-squares) from a
    range of degrees up to n = max_deg. The LASSO regression minimises MSE and
    penalizes the size of the parameter vector using L1-norm, which leads to
    fewer coefficients in the fitted model.

    - The 'alpha' parameter (amount of penalization) is selected by k-fold CV.
    - Predicts fitted model on given values 'x_pred' (default use 'x').
    - Supports NaNs.

    """
    ind, = np.where((~np.isnan(x)) & (~np.isnan(y)))
    x_, y_ = x[ind], y[ind]
    X_ = dmatrix('C(x_, Poly)')
    if x_pred is None:
        X = dmatrix('C(x, Poly)')      # predict on original values
    else:
        X = dmatrix('C(x_pred, Poly)') # predict on given values
    lasso = LassoCV(cv=cv, copy_X=True, normalize=True, max_iter=max_iter)
    lasso = lasso.fit(X_[:,1:max_deg+1], y_)
    y_pred = lasso.predict(X[:,1:max_deg+1])
    if return_model:
        y_pred = [y_pred, lasso]
    return y_pred
