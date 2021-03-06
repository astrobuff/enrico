import os
from distutils.version import LooseVersion
import numpy as np
import pyfits
import pyLikelihood
import matplotlib
matplotlib.use('Agg')
matplotlib.rc('font', **{'family': 'serif', 'serif': ['Computer Modern'], 'size': 15})
matplotlib.rc('text', usetex=True)
import matplotlib.pyplot as plt
from enrico.constants import MEV_TO_ERG, ERG_TO_MEV
from enrico.config import get_config
from enrico import utils
from enrico import Loggin
from enrico.extern.astropy_bayesian_blocks import bayesian_blocks

class Params:
    """Collection of Plotting parameters like Energy bounds,
    colors, file name, etc...."""
    def __init__(self, srcname, Emin=100, Emax=3e5,
                 PlotName="LAT_SED", LineColor=2,
                 PointColor = 1, N = 2000):
        self.Emin = Emin #Energy bounds
        self.Emax = Emax
        self.N = N #Number of points for the TGraph
        self.srcname = srcname # Source of interest
        self.PlotName = PlotName #file name
        #color options
        self.LineColor = LineColor
        self.PointColor = PointColor


class Result(Loggin.Message):
    """Helper class to get the results from a (Un)BinnedAnalysis object
    and compute the SED and errors"""
    def __init__(self, Fit, pars):
        super(Result,self).__init__()
        Loggin.Message.__init__(self)

        self.Fit = Fit
        self.Model = Fit[pars.srcname].funcs['Spectrum'].genericName()
        self.ptsrc = pyLikelihood.PointSource_cast(Fit[pars.srcname].src)
        self.covar = np.array(utils.GetCovar(pars.srcname, self.Fit, False))
        self.srcpars = pyLikelihood.StringVector()
        Fit[pars.srcname].src.spectrum().getFreeParamNames(self.srcpars)

    def GetDecorrelationEnergy(self,par):
        self.E, self.SED = self.MakeSED(par)
        self.Err         = self.MakeSEDError(par)
        i=np.argmin(self.Err/self.SED)
        self.decE       = self.E[i]
        self.decFlux    = self.SED[i]/self.E[i]**2*ERG_TO_MEV
        self.decFluxerr = self.Err[i]/self.E[i]**2*ERG_TO_MEV
        self.decSED     = self.SED[i]
        self.decSEDerr  = self.Err[i]

    def _DumpSED(self,par):
        """Save the energy, E2.dN/dE, and corresponding  error in an ascii file
        The count and residuals plot vs E is also made"""

        try:
            self.decE
        except NameError:
            self.GetDecorrelationEnergy(par)

        self.info("Decorrelation energy : %4.2e MeV"% self.decE)
        self.info("Diffential flux  at the Decorrelation energy : %2.2e +/-  %2.2e ph/cm2/s/MeV" \
                %(self.decFlux, self.decFluxerr))
        self.info("SED value at the Decorrelation energy : %2.2e +/-  %2.2e erg/cm2/s" \
                %(self.decSED, self.decSEDerr))

        try:
            self.CountsPlot(par)
        except:
            raise
        # Save all in ascii file
        # log(E)  log (E**2*dN/dE)   log(E**2*dN/dE_err)  is_dot (0,1) is_upper (0,1)
        save_file = open(par.PlotName + '.dat', 'w')
        save_file.write("# log(E)  log (E**2*dN/dE)   Error on log(E**2*dN/dE)   \n")
        for i in xrange(par.N):
            save_file.write("%12.4e  %12.4e  %12.4e \n" % (self.E[i], self.SED[i], self.Err[i]))
        save_file.close()

    def MakeFlux(self, params):
        """Compute differential Flux distribution and
        corresponding energy and return a numpy array"""
        E = np.logspace(np.log10(params.Emin), np.log10(params.Emax), params.N)
        Flux = np.zeros(params.N)
        for i in xrange(params.N):
            Flux[i] = self.dNde(E[i])
        return E, Flux

    def MakeSED(self, pars):
        """Compute Spectral energy distribution and corresponding energy
        and return a numpy array"""
        E = np.logspace(np.log10(pars.Emin), np.log10(pars.Emax), pars.N)
        nuFnu = np.zeros(pars.N)
        for i in xrange(pars.N):
            nuFnu[i] = MEV_TO_ERG  * E[i] ** 2 * self.dNde(E[i]) #Mev to Ergs
        return E, nuFnu

    def MakeSEDError(self, pars):
        """@todo: document me"""
        estep = np.log(pars.Emax / pars.Emin) / (pars.N - 1)
        energies = pars.Emin * np.exp(estep * np.arange(np.float(pars.N)))
        err = np.zeros(pars.N)
        j = 0
        for ene in energies:
            arg = pyLikelihood.dArg(ene)
            partials = np.zeros(len(self.srcpars))
            for i in xrange(len(self.srcpars)):
                x = self.srcpars[i]
                partials[i] = self.ptsrc.spectrum().derivByParam(arg, x)
            err[j] = np.sqrt(np.dot(partials, np.dot(self.covar, partials)))
            j += 1

        return MEV_TO_ERG  * energies ** 2 * err #Mev to Ergs

    def dNde(self, energy):
        arg = pyLikelihood.dArg(energy)
        return self.ptsrc.spectrum()(arg)

    def CountsPlot(self, Parameter):
        """@todo: document me"""
        imName = "tmp.fits"
        filebase = Parameter.PlotName

        total   = np.array([])
        obs     = np.array([])
        obs_err = np.array([])
        emax    = np.array([])
        emin    = np.array([])
        src     = np.array([])

        # Summed Likelihood has no writeCountsSpectra
        # but we can do it component by component
        for comp in self.Fit.components:
            #self.Fit.writeCountsSpectra(imName)
            comp.writeCountsSpectra(imName)
            image = pyfits.open(imName)

            #loop on the source names to find the good one
            j = 0
            for ID in image[1].data.names:
                if ID == Parameter.srcname:
                    indice = j
                j += 1

            for jn in xrange(len(image[3].data.field(0))):
                energymin = image[3].data.field(1)[jn]
                energymax = image[3].data.field(0)[jn]
                if energymax in emax and energymin in emin:
                    k = np.where(energymax==emax)
                    obs[k]     = obs[k] + image[1].data.field(0)[jn]
                    obs_err[k] = np.sqrt(obs[k])
                    src[k]     = src[k] + image[1].data.field(indice)[jn]
                    for i in xrange(len(image[1].data.names) - 1):
                        total[k] = total[k] + image[1].data.field(i + 1)[jn]
                else:
                    emax    = np.append(emax, energymax)
                    emin    = np.append(emin, energymin)
                    obs     = np.append(obs,image[1].data.field(0)[jn])
                    obs_err = np.append(obs_err, np.sqrt(image[1].data.field(0)[jn]))
                    src     = np.append(src, image[1].data.field(indice)[jn])
                    total   = np.append(total,0)
                    for i in xrange(len(image[1].data.names) - 1):
                        total[-1] = total[-1] + image[1].data.field(i + 1)[jn]

        other = np.array(total - src)
        Nbin  = len(src)
        E = np.array((emax + emin) / 2.)
        err_E = np.array((emax - emin) / 2.)

        total = np.array(total)
        residual = np.zeros(Nbin)
        Dres = np.zeros(Nbin)

        plt.figure()
        plt.loglog()
        plt.title('Counts plot')
        plt.xlabel("E (MeV) ")
        plt.ylabel("Counts / bin")
        plt.errorbar(E,obs,xerr=err_E,yerr=obs_err,fmt='o',color="red",ls='None',label="Data")
        plt.plot(E,other,'--',color="blue",label=Parameter.srcname)
        plt.plot(E,src,'-',color="green",label="Other Sources")
        plt.plot(E,total,'-',ls='None',label="All Sources")
        plt.legend()
        plt.savefig(filebase + "_CountsPlot.png", dpi=150, facecolor='w', edgecolor='w',
            orientation='portrait', papertype=None, format=None,
            transparent=False, bbox_inches=None, pad_inches=0.1,
            frameon=None)

        plt.figure()
        plt.title('Residuals plot')
        plt.semilogx()

        for i in xrange(Nbin):
            try:
                residual[i] = (obs[i] - total[i]) / total[i]
                Dres[i] = (obs_err[i] / total[i])
            except:
                residual[i] = 0.
                Dres[i] = 0.
            if residual[i] == -1.:
               residual[i] = 0.

        ymin = min(residual) - max(Dres)
        ymax = max(residual) + max(Dres)
        plt.ylim(ymax = ymax, ymin = ymin)
        plt.xlim(xmin = min(E)*0.3, xmax = max(E)*2)
        plt.xlabel("E (MeV) ")
        plt.ylabel("(counts-model)/model")
        plt.errorbar(E,residual,xerr=err_E,yerr=Dres,fmt='o',color="red",ls='None',label="Data")
        zero = np.zeros(2)
        Ezero = np.array([0, 1e10])
        plt.plot(Ezero,zero,'-',color='black')
        plt.savefig(filebase + "ResPlot.png", dpi=150, facecolor='w', edgecolor='w',
            orientation='portrait', papertype=None, format=None,
            transparent=False, bbox_inches=None, pad_inches=0.1,
            frameon=None)
        os.system("rm " + imName)
        image.close()


# def PlotFoldedLC(Time, TimeErr, Flux, FluxErr, tag="Flux (photon cm^{-2} s^{-1})"):
#     _, tgraph, arrows = PlotLC(Time, TimeErr, Flux, FluxErr, tag)

#     xmin = 0
#     xmax = 1
#     if max(FluxErr)==0:
#         ymin = 0.
#         ymax = max(Flux)*1.3
#     else:
#         ymin = np.min(min(Flux) - max(FluxErr) * 1.3, 0.)
#         ymax = (max(Flux) + max(FluxErr)) * 1.3
#     gh = ROOT.TH2F("ghflux", "", 80, xmin, xmax, 100, ymin, ymax)
#     gh.SetStats(000)
#     gh.SetXTitle("Orbital Phase")
#     gh.SetYTitle(tag)
#     return gh, tgraph, arrows

def GetDataPoints(config,pars):
    """Collect the data points/UL and generate a TGraph for the points
    and a list of TArrow for the UL. All is SED format"""

    #Preparation + declaration of arrays
    arrows = []
    NEbin = int(config['Ebin']['NumEnergyBins'])
    lEmax = np.log10(float(config['energy']['emax']))
    lEmin = np.log10(float(config['energy']['emin']))
    Epoint = np.zeros(NEbin)
    EpointErrp = np.zeros(NEbin)
    EpointErrm = np.zeros(NEbin)
    Fluxpoint = np.zeros(NEbin)
    FluxpointErrp = np.zeros(NEbin)
    FluxpointErrm = np.zeros(NEbin)
    uplim = np.zeros(NEbin,dtype=int)
    ener = np.logspace(lEmin, lEmax, NEbin + 1)

    mes = Loggin.Message()
    mes.info("Save Ebin results in ",pars.PlotName+".Ebin.dat")
    dumpfile = open(pars.PlotName+".Ebin.dat",'w')
    dumpfile.write("# Energy (MeV)\tEmin (MeV)\tEmax (MeV)\tE**2. dN/dE (erg.cm-2s-1)\tGaussianError\tMinosNegativeError\tMinosPositiveError\n")

    from enrico.constants import EbinPath
    for i in xrange(NEbin):#Loop over the energy bins
        #E = int(pow(10, (np.log10(ener[i + 1]) + np.log10(ener[i])) / 2))
        filename = (config['out'] + '/'+EbinPath+str(NEbin)+'/' + config['target']['name'] +
                    "_" + str(i) + ".conf")

        try:#read the config file of each data points
            CurConf = get_config(filename)
            mes.info("Reading "+filename)
            results = utils.ReadResult(CurConf)
        except:
            mes.warning("cannot read the Results of energy bin "+ str(i))
            continue
        #fill the energy arrays
        Epoint[i] = results.get("Scale")
        if Epoint[i] in [results.get("Emin"),results.get("Emax")]:
            Epoint[i] = 10**((np.log10(results.get("Emin"))+np.log10(results.get("Emax")))/2.)
            #Epoint[i] = int(pow(10, (np.log10(ener[i + 1]) + np.log10(ener[i])) / 2))

        EpointErrm[i] = Epoint[i] - results.get("Emin")
        EpointErrp[i] = results.get("Emax") - Epoint[i]
        dprefactor = 0

        #Compute the flux or the UL (in SED format)
        if results.has_key('Ulvalue'):
            PrefUl = utils.Prefactor(results.get("Ulvalue"),results.get("Index"),
                                    results.get("Emin"),results.get("Emax"),Epoint[i])
            Fluxpoint[i] = MEV_TO_ERG  * PrefUl * Epoint[i] ** 2
            uplim[i] = 1
        else : #Not an UL : compute points + errors
            Fluxpoint[i] = MEV_TO_ERG  * results.get("Prefactor") * Epoint[i] ** 2

        dprefactor = results.get("dPrefactor")
        try:
            down = abs(results.get("dPrefactor-"))
            up = results.get("dPrefactor+")
            if down==0 or  up ==0 :
              mes.error("cannot get Error value")
            FluxpointErrp[i] = MEV_TO_ERG  * up * Epoint[i] ** 2
            FluxpointErrm[i] = MEV_TO_ERG  * down * Epoint[i] ** 2
        except:
            try:
                err = MEV_TO_ERG  * dprefactor * Epoint[i] ** 2
                FluxpointErrp[i] = err
                FluxpointErrm[i] = err
            except:
                pass

        mes.info("Energy bins results")
        print "Energy = ",Epoint[i]
        #Save the data point in a ascii file
        if results.has_key('Ulvalue'):
            dumpfile.write(str(Epoint[i])+"\t"+str(results.get("Emin"))+"\t"+str( results.get("Emax"))+"\t"+str(Fluxpoint[i])+"\t0\t0\t0\n")
            print "E**2. dN/dE = ",Fluxpoint[i]
        else:
            dumpfile.write(str(Epoint[i])+"\t"+str(results.get("Emin"))+"\t"+str( results.get("Emax"))+"\t"+str(Fluxpoint[i])+"\t"+str( MEV_TO_ERG  * dprefactor * Epoint[i] ** 2)+"\t"+str(FluxpointErrm[i])+"\t"+str(FluxpointErrp[i])+"\n")
            print "E**2. dN/dE = ",Fluxpoint[i]," + ",FluxpointErrp[i]," - ",FluxpointErrm[i]
    dumpfile.close()
    return Epoint, Fluxpoint, EpointErrm, EpointErrp, FluxpointErrm, FluxpointErrp, uplim

def plot_errorbar_withuls(x,xerrm,xerrp,y,yerrm,yerrp,uplim,bblocks=False):
    """ plot an errorbar plot with upper limits. Optionally compute and draw bayesian blocks (bblocks) """
    # plt.errorbar(Epoint, Fluxpoint, xerr=[EpointErrm, EpointErrp], yerr=[FluxpointErrm, FluxpointErrp],fmt='o',color='black',ls='None',uplims=uplim)
    uplim = np.asarray(uplim,dtype=bool) # It is an array of 1 and 0s, needs to be a bool array.
    # make sure that the arrays are numpy arrays and not lists.
    x = np.asarray(x)
    xerrm = np.asarray(xerrm)
    xerrp = np.asarray(xerrp)
    y = np.asarray(y)
    yerrm = np.asarray(yerrm)
    yerrp = np.asarray(yerrp)
    # Get the strict upper limit (best fit value + error, then set the error to 0 and the lower error to 20% of the value)
    y[uplim] += yerrp[uplim]
    yerrm[uplim] = 0
    yerrp[uplim] = 0

    optimal_markersize = (0.5+4./(1.+np.log10(len(y))))

    # Plot the significant points
    plt.errorbar(x[~uplim], y[~uplim],
        xerr=[xerrm[~uplim], xerrp[~uplim]],
        yerr=[yerrm[~uplim], yerrp[~uplim]],
        fmt='o',ms=optimal_markersize,capsize=0,zorder=10,
        color='black',ls='None',uplims=False,label='LAT data')

    # Plot the upper limits. For some reason, matplotlib draws the arrows inverted for uplim and lolim [?]
    # This is a known issue fixed in matplotlib 1.4: https://github.com/matplotlib/matplotlib/pull/2452
    if LooseVersion(matplotlib.__version__) < LooseVersion("1.4.0"):
        plt.errorbar(x[uplim], y[uplim],
            xerr=[xerrm[uplim], xerrp[uplim]],
            yerr=[yerrm[uplim], yerrp[uplim]],
            fmt='o',markersize=0,capsize=0,zorder=-1,
            color='0.50',ls='None',lolims=False)
        plt.errorbar(x[uplim], 0.8*y[uplim],
            yerr=[0.2*y[uplim], 0.2*y[uplim]],
            fmt='o',markersize=0,capsize=optimal_markersize/1.5,zorder=-1,
            color='0.50',ls='None',lolims=True)
    else:
        plt.errorbar(x[uplim], y[uplim],
            xerr=[xerrm[uplim], xerrp[uplim]],
            yerr=[yerrm[uplim], yerrp[uplim]],
            fmt='o',markersize=0,capsize=0,zorder=-1,
            color='0.50',ls='None',uplims=False)
        plt.errorbar(x[uplim], 0.8*y[uplim],
            yerr=[0.2*y[uplim], 0.2*y[uplim]],
            fmt='o',markersize=0,capsize=optimal_markersize/1.5,zorder=-1,
            color='0.50',ls='None',uplims=True)

    if bblocks:
        yerr = 0.5*(yerrm+yerrp)
        # Set the value and error for the uls.
        yerr[uplim] = y[uplim] #min(y[yerr>0]+yerr[yerr>0])
        y[uplim] = 0
        edges = bayesian_blocks(x,y,yerr,fitness='measures',p0=0.5)
        #edges = bayesian_blocks(x[yerr>0],y[yerr>0],yerr[yerr>0],fitness='measures',p0=0.1)
        xvalues = 0.5*(edges[:-1]+edges[1:])
        xerrors = 0.5*(edges[1:]-edges[:-1])
        yvalues = []
        yerrors = []
        for k in xrange(len(edges)-1):
            xmin,xmax = edges[k],edges[k+1]
            filt = (x>=xmin)*(x<=xmax)*(yerr>0)
            sum_inv_square = np.sum(1./yerr[filt]**2)
            yvalues.append(np.sum(y[filt]/yerr[filt]**2)/sum_inv_square)
            yerrors.append(1./np.sqrt(sum_inv_square))

        yvalues = np.asarray(yvalues)
        yerrors = np.asarray(yerrors)

        # Plot the significant points
        ystep = []
        ystepmin = []
        ystepmax = []
        xstep = []
        for k in xrange(len(xvalues)):
            for _ in xrange(2):
                ystep.append(yvalues[k]) # 3 values, to mark the minimum and center
                ystepmin.append(yvalues[k]-yerrors[k]) # 3 values, to mark the minimum and center
                ystepmax.append(yvalues[k]+yerrors[k]) # 3 values, to mark the minimum and center
            xstep.append(xvalues[k]-xerrors[k])
            xstep.append(xvalues[k]+xerrors[k])

        plt.step(xstep, ystep,
            color='#d62728',zorder=-10,
            ls='solid')
        plt.fill_between(xstep, ystepmin, ystepmax,
            color='#d62728',zorder=-10, alpha=0.5)
        plt.errorbar(xvalues, yvalues,
            xerr=xerrors,yerr=yerrors,
            marker=None,ms=0,capsize=0,color='#d62728',zorder=-10,
            ls='None',label='bayesian blocks')

        plt.legend(loc=0,fontsize='small',numpoints=1)

def PlotSED(config,pars):
    """plot a nice SED with a butterfly and points"""

    # Read the ascii file where the butterfly is stored
    filebase = utils._SpecFileName(config)

    lines = open(filebase + '.dat', 'r').readlines()
    SED = []
    E = []
    Err = []

    for i in xrange(len(lines) - 1):
        words = lines[i + 1].split()
        if float(words[0])<pars.Emax :
            E.append(float(words[0]))
            SED.append(float(words[1]))
            Err.append(float(words[2]))
    ilen = len(SED)

    #From dN/dE to SED
    Fluxp = np.array(SED)*np.exp(np.array(Err)/np.array(SED))
    Fluxm =  np.array(SED)*np.exp(-np.array(Err)/np.array(SED))
    ErrorFlux = np.zeros(2 * ilen + 1)
    ErrorE = np.zeros(2 * ilen + 1)

    #Compute the butterfly and close it
    for i in xrange(ilen):
        ErrorFlux[i] = Fluxp[i]
        ErrorE[i] = E[i]
    for i in xrange(ilen):
        ErrorFlux[ilen + i] = Fluxm[ilen - i - 1]
        ErrorE[ilen + i] = E[ilen - i - 1]
    ErrorFlux[-1] = Fluxp[0]
    ErrorE[-1] = E[0]

    #Actually make the plot
    plt.figure()
    plt.title(pars.PlotName.split("/")[-1].replace('_','\_'))
    name = pars.PlotName.split("/")[-1]
    plt.loglog()

    plt.xlabel(r"Energy (MeV)")
    plt.ylabel(r"$\mathrm{E^2\ dN/dE}\ \mathrm{(erg\ cm^{-2} s^{-1})}$")
    plt.plot(E,SED,"-r",label='LAT model')
    plt.plot(ErrorE,ErrorFlux,"-r")

    #Plot points
    NEbin = int(config['Ebin']['NumEnergyBins'])
    if NEbin > 0:
        Epoint, Fluxpoint, EpointErrm, EpointErrp, FluxpointErrm, FluxpointErrp, uplim = GetDataPoints(config,pars) #collect data points
        plot_errorbar_withuls(Epoint,EpointErrm,EpointErrp,Fluxpoint,FluxpointErrm,FluxpointErrp,uplim)

    #print uplim
    #print FluxpointErrm
    #print FluxpointErrp

    #Set meaningful axes limits
    xlim = plt.xlim()
    ylim = plt.ylim()
    xlim = (max([20,xlim[0]]),min([2e6,xlim[1]]))
    ylim = (max([1e-13,ylim[0]]),min([1e-8,ylim[1]]))
    plt.xlim(xlim)
    plt.ylim(ylim)
    # turn them into log10 scale
    #xticks = plt.xticks()[0]
    #xticklabels = np.array(np.log10(xticks),dtype=int)
    #plt.xticks(xticks,xticklabels)
    #plt.xlabel('$\mathrm{\log_{10}\mathbf{(Energy)} \\ \\ [MeV]}$')

    plt.legend(fontsize='small',ncol=1,\
               loc=3,numpoints=1)#,framealpha=0.75)


    #Upper horizontal secondary axis with frequency
    #Plt2 = plt.twiny()
    #Plt2.set_xscale('log')
    #Plt2.set_xlim(2.417990504024163e+20 *np.array(xlim))
    #Plt2.set_xticklabels(np.array(np.log10(Plt2.get_xticks()),dtype=int))
    #Plt2.set_xlabel('$\mathrm{\log_{10}\mathbf{(Frequency)} \\ \\ [Hz]}$')

    #save the canvas
    #plt.grid()
    plt.savefig("%s.png" %filebase, dpi=150, facecolor='w', edgecolor='w',
            orientation='portrait', papertype=None, format=None,
            transparent=False, bbox_inch=None, pad_inches=0.1,
            frameon=None)

def PlotUL(pars,config,ULFlux,Index):

    #Compute the SED
    E = np.logspace(np.log10(pars.Emin), np.log10(pars.Emax), pars.N)
    SED = MEV_TO_ERG  * E ** 2 * (-Index+1)*ULFlux* np.power(E,-Index)/(np.power(pars.Emax,-Index+1)-np.power(pars.Emin,-Index+1))

    #Actually make the plot
    plt.xlabel(r"E [MeV]")
    plt.ylabel(r"$E^{2}dN/dE [ erg.cm^{-2}.s^{-1} ]$")
    plt.loglog()
    plt.plot(E,SED,"-",color='black')

    # Plot the upper limits. For some reason, matplotlib draws the arrows inverted for uplim and lolim [?]
    # This is a known issue fixed in matplotlib 1.4: https://github.com/matplotlib/matplotlib/pull/2452
    if LooseVersion(matplotlib.__version__) < LooseVersion("1.4.0"):
        plt.errorbar([E[0],E[-1]], [SED[0],SED[-1]],  yerr=[SED[0]*0.8,SED[-1]*0.8],fmt='.',color='black',ls='None',lolims=[1,1])
    else:
        plt.errorbar([E[0],E[-1]], [SED[0],SED[-1]],  yerr=[SED[0]*0.8,SED[-1]*0.8],fmt='.',color='black',ls='None',uplims=[1,1])

    #save the plot
    filebase = utils._SpecFileName(config)
    plt.savefig(filebase + '.png', dpi=150, facecolor='w', edgecolor='w',
            orientation='portrait', papertype=None, format=None,
            transparent=False, bbox_inches=None, pad_inches=0.1,
            frameon=None)
