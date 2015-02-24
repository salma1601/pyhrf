import os
import os.path as op
import numpy as np
from scipy.io.matlab import savemat

import matplotlib.pyplot as plt

from pyhrf.paradigm import restarize_events
from pyhrf.boldsynth.hrf import getCanoHRF
from pyhrf.ndarray import xndarray, MRI3Daxes
from pyhrf.core import FmriData
from pyhrf.plot import plot_func_slice, autocrop, plot_palette
from pyhrf.plot import set_ticks_fontsize
from pyhrf.tools import add_suffix

import matplotlib
from matplotlib.colors import normalize, LinearSegmentedColormap
matplotlib.rcParams['text.latex.preamble'] = [r"\usepackage{amsmath}"]

from matplotlib import rc
rc('text', usetex=True)
rc('font', family='sans serif')


def cmstring_to_mpl_cmap(s):
    lrgb = s.split('#')
    r = [float(v) for v in lrgb[0].split(';')]
    g = [float(v) for v in lrgb[1].split(';')]
    b = [float(v) for v in lrgb[2].split(';')]

    cdict = {'red': (), 'green': (), 'blue': ()}
    for iv in xrange(0, len(r), 2):
        cdict['red'] += ((r[iv], r[iv + 1], r[iv + 1]), )
    for iv in xrange(0, len(b), 2):
        cdict['blue'] += ((b[iv], b[iv + 1], b[iv + 1]), )
    for iv in xrange(0, len(g), 2):
        cdict['green'] += ((g[iv], g[iv + 1], g[iv + 1]), )

    return LinearSegmentedColormap('mpl_colmap', cdict, 256)

fs = 35  # fontsize
# color map used for plots of RLs:
cmap_string = '0;0;0.5;0.0;0.75;1.0;1.;1.0#' \
                '0;0;0.5;1;0.75;1;1;0.#'       \
                '0;0;0.25;1;0.5;0;1;0.'
cmap = cmstring_to_mpl_cmap(cmap_string)


def gen_spm_regs(subject, nscans, tr, dt, paradigm_fn):
    
    output_fn = './archives/' + subject + '/ASLf/regressors_ASLf.mat'

    if not op.exists(op.dirname(output_fn)):
        raise Exception('Folders containing preprocessed data not found. '\
                        'Run Batch_HEROES_ASLf_2014.m with preprocs only '\
                        'before launching this script')

    if not op.exists(paradigm_fn):
        raise Exception('Paradigm file not found in current directory. '
                        'Should have been generated by another script')

    condition_order = ['clicGaudio', 'clicGvideo',
                       'clicDaudio', 'clicDvideo',
                       'phraseaudio', 'phrasevideo']
    dm, rn = build_matrix(paradigm_fn, output_fn, nscans, tr, dt,
                 cond_order=condition_order)
    return dm, rn


def build_matrix(paradigm_fn, output_fn, nscans, tr, dt, plot=False,
                 save_dmat_png=False, cond_order=None):
    """
    cond_order is used to sort the column of the design matrix
    """
    load_paradigm(paradigm_fn)
    onsets, dur = load_paradigm(paradigm_fn)
    onsets = dict((n, o) for n, o in onsets.iteritems() if n != 'final_rest')
    dur = dict((n, o) for n, o in dur.iteritems() if n != 'final_rest')
    print 'Onsets description:'
    print_descrip_onsets(onsets)
    ons = onsets
    nbConditions = len(ons)
    nregressors = 2 * ((nbConditions) + 1)

    # HRF
    tMax = tr * nscans
    hrf_length = 25.
    thc, hc = getCanoHRF(hrf_length, dt)
    # Omega
    from pyhrf.sandbox.physio_params import PHY_PARAMS_KHALIDOV11 as phy_params
    from pyhrf.sandbox.physio_params import linear_rf_operator
    Omega = linear_rf_operator(hrf_length / dt + 1, phy_params, dt,
                                calculating_brf=False)
    # PRF
    pc = np.dot(Omega, hc)
    """import matplotlib.pyplot as plt
    plt.plot(pc)
    plt.plot(hc)
    plt.show()"""

    x = np.zeros((nscans, nregressors))
    print x.shape
    convMode = 'full'
    xconv = np.zeros((nscans, nregressors))
    reg_names = []
    if cond_order is None:
        cond_order = ons.iterkeys()

    j = 0
    for i, cname in enumerate(cond_order):
        o = ons[cname]
        d = dur[cname]
        x[:, i] = restarize_events(o, d, tr, tMax)[:nscans]
        xconv[:, j] = np.convolve(x[:, i], hc * 3., \
                                  mode=convMode)[:len(x[:, i])]
        reg_names.append(cname + '_BOLD')
        j += 1
    x[:, j] = 1.
    xconv[:, j] = 1.  # max(hc)
    j += 1
    reg_names.append('baseline')
    vmax = max(x.max(), xconv.max())
    vmin = min(x.min(), xconv.min())

    tag_ctrl_weights = np.ones(nscans)
    tag_ctrl_weights[1::2] = -1
    for i, cname in enumerate(cond_order):
        o = ons[cname]
        d = dur[cname]
        x[:, i] = restarize_events(o, d, tr, tMax)[:nscans]
        xconv[:, j] = np.convolve(x[:, i], pc * 3., \
                                  mode=convMode)[:len(x[:, i])]
        xconv[:, j] *= tag_ctrl_weights
        reg_names.append(cname + '_perf')
        j += 1
    x[:, j] = 1.
    xconv[:, j] = 1.  # max(pc)
    reg_names.append('perf_basale')
    ib = reg_names.index('baseline')
    xconv = xconv[:, range(0, ib) + range(ib + 1, xconv.shape[1])]
    
    import pyhrf.vbjde.vem_tools as vt
    ndrift = 4
    drift = vt.PolyMat(nscans, ndrift, tr)
    xconv = np.append(xconv, drift, axis=1)
    for d in xrange(0, drift.shape[1]):
        reg_names.append('drift'+str(d))
    reg_names.pop(ib)
    to_save = {'r': xconv,
               'reg_names': reg_names}
    print 'Save regressors to:', output_fn
    savemat(output_fn, to_save)

    extent = (0, x.shape[1], x.shape[0] * tr, 0)
    if plot:
        n = plt.Normalize(vmin, vmax)
        plt.matshow(x, aspect='.15', cmap=plt.cm.gray_r,
                    extent=extent)
        plt.title('onsets')

    if save_dmat_png:
        fn = './design_matrix_onsets_only.png'
        plt.colorbar(shrink=.35)
        plt.savefig(fn, dpi=300)
        os.system('convert %s -trim %s' % (fn, fn))

    if plot:
        plt.matshow(xconv, aspect='.15', cmap=plt.cm.gray_r,
                    extent=extent)
        plt.title('convolved onsets')

    if save_dmat_png:
        plt.colorbar(shrink=.35)
        fn = './design_matrix_convolved.png'
        plt.savefig(fn, dpi=300)
        os.system('convert %s -trim %s' % (fn, fn))
    return xconv, reg_names


def load_paradigm(fn):
    from collections import defaultdict

    fn_content = open(fn).readlines()
    onsets = defaultdict(list)
    durations = defaultdict(list)
    for line in fn_content:
        sline = line.split(' ')
        #print 'sline:', sline
        if len(sline) < 4:
            cond, onset, _ = sline
        else:
            #sess, cond, onset, duration, amplitude = sline
            sess, cond, onset, duration = sline
            duration = duration[:-1]
            if 0:            
                print 'sess = ', sess
                print 'cond = ', cond
                print 'onset = ', onset
                print 'duration = ', duration
                #0 "clicGaudio" 355.9 0
        onsets[cond.strip('"')].append(float(onset))
        durations[cond.strip('"')].append(float(duration))

    ons_to_return = {}
    dur_to_return = {}
    for cn, ons in onsets.iteritems():
        sorting = np.argsort(ons)
        ons_to_return[cn] = np.array(ons)[sorting]
        dur_to_return[cn] = np.array(durations[cn])[sorting]

    return ons_to_return, dur_to_return


def print_descrip_onsets(onsets):
    onsets = dict((n, o) for n, o in onsets.iteritems() \
                       if n not in ['blanc', 'blank'])
    all_onsets = np.hstack(onsets.values())
    diffs = np.diff(np.sort(all_onsets))
    #pprint(onsets)
    print 'mean ISI:', format_duration(diffs.mean())
    print 'max ISI:', format_duration(diffs.max())
    print 'min ISI:', format_duration(diffs.min())
    print 'first event:', format_duration(all_onsets.min())
    print 'last event:', format_duration(all_onsets.max())


def format_duration(dt):
    s = ''
    if dt / 3600 >= 1:
        s += '%dH' % int(dt / 3600)
        dt = dt % 3600
    if dt / 60 >= 1:
        s += '%dmin' % int(dt / 60)
        dt = int(dt % 60)
    s += '%1.3fsec' % dt
    return s


def plot_maps(plot_params, anat_fn, anat_slice_def, output_dir='./',
              flip_sign=False, crop_def=None, norm=None, cond='video'):

    ldata = []
    for p in plot_params:
        print 'load:', p['fn']
        print 'slice: ', p['slice_def']        
        c = xndarray.load(p['fn']).sub_cuboid(axial=ax_slice).reorient(\
                                                    ['coronal', 'sagittal'])
        #c.data[:,18:] = 0
        c.data *= p.get('scale_factor', 1.)
        if flip_sign:
            ldata.append(c.data * -1.)
        else:
            ldata.append(c.data)

    c_anat = xndarray.load(anat_fn).sub_cuboid(**anat_slice_def)
    c_anat.set_orientation(['coronal', 'sagittal'])

    all_data = np.array(ldata)
    mask = plot_params[0].get('mask')
    if cond == 'audio':
        mask[:, 18:] = 0            # WARNING!! Uncomment for audio
    m = np.where(mask > 0)
    all_data_masked = all_data[:, m[0], m[1]]
    if norm == None:
        norm = normalize(all_data_masked.min(), all_data_masked.max())
    print 'norm:', (all_data_masked.min(), all_data_masked.max())
    for data, plot_param in zip(all_data, plot_params):
        fn = plot_param['fn']

        #plt.figure()
        print 'fn:', fn
        print '->', (data.min(), data.max())
        plot_func_slice(data, anatomy=c_anat.data,
                        parcellation=mask,
                        func_cmap=cmap,
                        parcels_line_width=1., func_norm=norm)
        set_ticks_fontsize(fs)

        fig_fn = op.join(output_dir, '%s.png' % op.splitext(op.basename(fn))[0])
        print fig_fn
        output_fig_fn = fig_fn
        print output_fig_fn
        
        print 'Save to: %s' % output_fig_fn
        plt.savefig(output_fig_fn)
        autocrop(output_fig_fn)
        #plt.show()

        if crop_def is not None:
            # convert to jpg (avoid page size issues):
            output_fig_fn_jpg = op.splitext(output_fig_fn)[0] + '.jpg'
            os.system('convert %s %s' % (output_fig_fn, output_fig_fn_jpg))
            # crop and convert back to png:
            output_fig_fn_cropped = add_suffix(output_fig_fn, '_cropped')
            print 'output_fig_fn_cropped:', output_fig_fn_cropped
            os.system('convert %s -crop %s +repage %s' \
                      % (output_fig_fn_jpg, crop_def, output_fig_fn_cropped))
    return norm
    

def plot_regressor(reg_fn):
    reg = xndarray.load(reg_fn)
    print reg.data.shape
    
    return


if __name__ == '__main__':
    subjects = ['AINSI_010_TV', 'AINSI_001_GC', 'AINSI_007_AB', \
                'AINSI_006_FM', 'AINSI_005_SB', \
                'AINSI_004_AE', 'AINSI_003_CP', 'AINSI_002_EV']
    for subject in subjects:
        nscans = 291
        tr = 3.
        dt = .5
        paradigm_fn = './archives/paradigm.csv'

        # Design matrix
        dm, rn = gen_spm_regs(subject, nscans, tr, dt, paradigm_fn)

        # BOLD data
        data_dir = op.join('./archives', subject)
        anat_dir = op.join(data_dir, 'anat')        
        bold_fn = op.join(data_dir, 'ASLf', 'funct', 'normalise', \
                          'wr' + subject + '_ASLf_correctionT1.nii')
        gm_fn = op.join(data_dir, 'anat', 'wc1' + subject + '_anat-0001.nii')
        gm = xndarray.load(gm_fn).data
        bold = xndarray.load(bold_fn).data
        bold_mean = np.mean(bold[np.where(gm > 0)])
        bold_range = (np.max(bold) - np.min(bold))
        print bold.shape
        print len(bold[:,:,:,0].flatten())
        del bold
        del gm
        print 'BOLD mean', bold_mean
        print 'BOLD range', bold_range
        roi_mask_fn = op.join(data_dir, 'ASLf', 'parcellation',
                              'parcellation_func.nii')
        fdata = FmriData.from_vol_files(mask_file=roi_mask_fn,
                                        paradigm_csv_file=paradigm_fn,
                                        bold_files=[bold_fn], tr=tr)
        Y = (fdata.bold - bold_mean) * 100 / bold_range
        print 'mean bold = ', np.mean(Y)
        print Y.shape

        #GLM
        from nipy.labs.glm import glm
        my_glm = glm.glm()
        """residuals_model: "spherical", "ar1"
        fit_method: "ols", "kalman" (If residuals_model is "ar1" then method
            is set to "kalman" and this argument is ignored)"""
        residuals_model = 'spherical'
        fit_method = 'ols'
        print Y.shape
        print dm.shape
        my_glm.fit(Y, dm, method=fit_method, model=residuals_model)
        rescale_results = False
        if rescale_results:
            # Rescale by the norm of each regressor in the design matrix
            dm_reg_norms = (dm ** 2).sum(0) ** .5
            for ib in xrange(my_glm.beta.shape[0]):
                my_glm.beta[ib] = my_glm.beta[ib] * dm_reg_norms[ib]
                #my_glm.beta[ib] = my_glm.beta[ib] * rescale_factor[ib]

        # Save regressors
        output_dir1 = op.join(data_dir, 'glm_analysis')
        roi_mask = fdata.roiMask
        roi_mask[np.where(roi_mask > 0)] = 1
        print 'ROI mask '
        print roi_mask.shape
        print roi_mask[np.where(roi_mask > 0)]
        print np.sum(np.where(roi_mask>0)*1)
        outputs = {}
        if not op.exists(output_dir1):
            os.makedirs(output_dir1)
        regressors = []
        print my_glm.beta.shape[0]
        for ib in xrange(my_glm.beta.shape[0]):
            print ib
            print rn[ib]
            print my_glm.beta[ib]
            print my_glm.beta[ib].shape
            output0 = xndarray(my_glm.beta[ib], value_label=rn[ib],
                              axes_names=['voxel'])
            fn = op.join(output_dir1, rn[ib] + '.nii')
            print roi_mask.shape
            output0 = output0.expand(roi_mask, 'voxel', MRI3Daxes)
            output0.save(fn)
    
            #prepare plots of RL maps:
            cond = 'audio'
            if cond == 'video':
                print cond
                ax_slice = 22
                crop_def = "140x181+170+0"
            else:
                ax_slice = 21
                crop_def = "140x181+0+174"
            slice_def = {'axial': ax_slice}  # , 'condition': cond}
            fig_fn = rn[ib] + '.png'
            mask = xndarray.load(roi_mask_fn)
            mask = mask.sub_cuboid(axial=ax_slice).reorient(\
                                            ['coronal', 'sagittal'])
            regressors.append({'fn': fn, 'slice_def': slice_def,
                               'mask': mask.data, 'output_fig_fn': fig_fn})

        anat_fn = op.join(anat_dir, 'w' + subject + '_anat-0001.nii')
        norm = plot_maps(regressors, anat_fn, {"axial": ax_slice * 3},
                         output_dir=output_dir1, crop_def=crop_def, cond=cond)
        plot_palette(cmap, norm, 45)
        palette_fig_fn = op.join(output_dir1, 'palette.png')
        plt.savefig(palette_fig_fn)
        autocrop(palette_fig_fn)
