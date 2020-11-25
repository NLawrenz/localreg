#!/usr/bin/env python

import numpy as np
from scipy.optimize import minimize, minimize_scalar
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from tqdm import tqdm
import sys
from frmt import print_table
from time import time, sleep
from scipy.stats import pearsonr

def read_RBF_data(fname):
    """
    Read dataset in Marchand's RBF format

    Parameters
    ----------
    fname: string
        filename

    Returns
    -------
    numpy.array where data[i,j] is row i, column j
    """
    data = []
    with open(fname) as file:
        file.readline()
        file.readline()
        for line in file:
            data.append(line.split())
    data = np.array(data, dtype=float)
    return data

def plot_data(data, net):
    """
    Plots data points and centers
    """
    for s, (i, j) in enumerate([[0,1], [0,2], [0,3], [1,2], [1,3], [2,3]]):
        plt.subplot(2,3,s+1)
        plt.plot(data[:,i], data[:,j], '.')
        net.plot_centers(plt.gca(), [i,j])
        plt.xlabel('$I_{}\,[\mu A]$'.format(i))
        plt.ylabel('$I_{}\,[\mu A]$'.format(j))
    plt.show()

def gaussian(t):
    return np.exp(-0.5*t**2)

# Error metrics:
# Pearson R
# Bias of relative and absolute
# Standard deviation of relative and absolute
# bias = np.mean
# stdev = np.std
# pearsonr = np.st

def rms_error(true, pred):
    e = pred-true
    return np.sqrt(np.sum(e**2)/len(e))

def rms_rel_error(true, pred):
    e = (pred-true)/true
    return np.sqrt(np.sum(e**2)/len(e))

def max_abs_error(true, pred):
    e = pred-true
    return np.max(np.abs(e))

def max_rel_error(true, pred):
    e = (pred-true)/true
    return np.max(np.abs(e))

def mean_abs_error(true, pred):
    e = pred-true
    return np.mean(np.abs(e))

def mean_rel_error(true, pred):
    e = (pred-true)/true
    return np.mean(np.abs(e))

def error_bias(true, pred):
    e = pred-true
    return np.mean(e)

def rel_error_bias(true, pred):
    e = (pred-true)/true
    return np.mean(e)

def error_std(true, pred):
    e = pred-true
    return np.std(e)

def rel_error_std(true, pred):
    e = (pred-true)/true
    return np.std(e)

class RBFnet(object):
    """
    A radial basis function (RBF) machine learning network.

    An arbitrary and possibly unknown function f(x) is approximated as a
    sum of radial basis functions g,

        f(x) ~ sum_i w_i g((x-c_i)/r)

    x is the input, possibly a vector. c_i and w_i are the centers and weights
    of basis function i, while r is its radius (the same for all basis
    functions). c_i, w_i and r are found during training, and are later used
    for prediction.

    A training (or prediction) data set is generally represented by arrays
    input (for x) and output (for y), where input[i,j] is data point i,
    independent variable j, and output[i] is data point j of the dependent
    variable, or output. Multiple output variables is simply represented
    by multiple RBFnet objects.
    """

    def __init__(self):
        self.input_shift = 0
        self.input_scale = 1
        self.output_shift = 0
        self.output_scale = 1

    def train(self, input, output, num=50, radius=None, rbf=gaussian,
              random_state=None, keep_aspect=False, verbose=False,
              measure=rms_error):
        """
        Train the RBF net to learn the relation between input and output.

        Training consists of three steps, which may be run in sequence as
        separate functions for maximum flexibility:

            1. adapt_normalization()
            2. compute_centers()
            3. fit_weights() or fit_weights_and_radius() if radius is None

        This method is simply a wrapper, that takes the same input as these
        functions. Only the most important input are listed below.

        Parameters
        ----------
        input: numpy.ndarray
            input[i,j] is data point i, independent variable j

        output: numpy.ndarray
            output[i] is data point i, dependent variable

        num: integer
            Number of radial basis functions.
        """

        self.adapt_normalization(input, output, keep_aspect)
        self.compute_centers(input, num, random_state)

        if radius is None:
            self.fit_weights_and_radius(input, output, rbf, verbose, measure)
        else:
            self.fit_weights(input, output, radius, rbf)

    def adapt_normalization(self, input, output, keep_aspect=False):
        """
        Adapt normalization of network to data, such that the normalized data
        inside the network will have zero mean and a standard deviation of one.

        Parameters
        ----------
        input: numpy.ndarray
            input[i,j] is data point i, independent variable j.

        output: numpy.ndarray
            output[i] is data point i, dependent variable.

        keep_aspect: bool
            Whether to scale all independent variables by the same factor,
            i.e., to keep the aspect ratio, or to scale them independently
            such that the standard deviation is one along each axis. It may
            make sense to keep the aspect ratio if the input variables have
            the same physical dimension.
        """
        self.output_shift = np.mean(output, axis=0)
        self.output_scale = np.std(output, axis=0)
        self.input_shift = np.mean(input, axis=0)
        if keep_aspect:
            self.input_scale = np.std(input)
        else:
            self.input_scale = np.std(input, axis=0)

    def compute_centers(self, input, num, random_state=None):
        """
        Compute the centers of the radial basis functions using K-means
        clustering.

        Parameters
        ----------
        input: numpy.ndarray
            input[i,j] is data point i, independent variable j.

        num: integer
            Number of radial basis functions.

        random_state: integer
            State of random number generator used to compute the centers. For
            exactly reproducible results this must be set manually. See
            sklearn.cluster.KMeans in Scikit-Learn.
        """
        # inp = (input-self.input_shift)/self.input_scale
        inp = self.normalize_input(input)
        clustering = KMeans(n_clusters=num, random_state=random_state).fit(inp)
        self.centers = clustering.cluster_centers_

    def fit_weights(self, input, output, radius=1, rbf=gaussian):
        """
        Fit the weights to the training data using exact linear least squares.

        Parameters
        ----------
        input: numpy.ndarray
            input[i,j] is data point i, independent variable j.

        output: numpy.ndarray
            output[i] is data point i, dependent variable.

        radius: float
            The radius of the basis functions on normalized data. When
            adapt_normalization is used, it is the radius in terms of
            the standard deviation, and is usually near one. This is
            a hyperparameter that can be tuned for minimum error.

        rbf: function
            Which radial basis function to use. The function should take a
            single scalar argument, and is shifted according to the centers and
            scaled according to the radius internally according to the
            following equation:

                rbf((input-center)/radius)

        """

        # inp = (input-self.input_shift)/self.input_scale
        # outp = (output-self.output_shift)/self.output_scale
        inp = self.normalize_input(input)
        outp = self.normalize_output(output)

        assert inp.shape[0]==outp.shape[0], \
            "different number of data points (length of axis 0) in input and output"

        assert inp.shape[1]==self.centers.shape[1], \
            "input has {} independent variables (length of axis 1) when fitting "\
            "weights, but had {} when computing centers"\
            .format(inp.shape[1], self.centers.shape[1])

        matrix = np.zeros((len(inp), len(self.centers)), dtype=float)
        for j in range(len(self.centers)):
            distance = np.linalg.norm(inp[:,:]-self.centers[j,:], axis=1)
            matrix[:,j] = rbf(distance/radius)

        coeffs, residual, rank, svalues = np.linalg.lstsq(matrix, outp, rcond=None)
        self.coeffs = coeffs
        self.residual = residual
        self.rbf = rbf
        self.radius = radius

    def fit_weights_and_radius(self, input, output, rbf=gaussian,
                               measure=rms_error, verbose=True,
                               method='powell', options=None,
                               tol=1e-6):
        """
        Similarly as the method fit_weights(), but this function uses an
        iterative minimizer to find the optimal radius.

        Parameters
        ----------
        measure: function
            The error measure used during optimization, with signature
            measure(true_values, predicted_values).

        verbose: bool
            Whether to show convergence status

        See fit_weights for: input, output, rbf
        See scipy.optimize.minimize for: method, options, tol
        """

            def fun(radius):
                self.fit_weights(input, output, radius, rbf)
                self.error = measure(output, self.predict(input))
                return self.error

            fmt = "{:<5}  {:<20}  {:<20}"

            if verbose:
                print(fmt.format("it.", "radius", "error"))

            self.fcall = 0
            def callback(params):
                if verbose:
                    self.fcall += 1
                    print(fmt.format(self.fcall, params[0], self.error))

            radius_0 = 1
            res = minimize(fun, radius_0, tol=1e-6,
                           options=options,
                           callback=callback,
                           method=method)

    def plot_centers(self, axis, indeps=(0,1), *args, **kwargs):
        """
        Plot the cluster centers projected onto a plane spanned by the axes
        of two of the independent variables.

        Parameters
        ----------
        axis: matplotlib.axis
            Axis on which to plot the centers

        indeps: list or tuple with two elements
            The independent variables to use as x- and y-axes

        Further accepts the same arguments as matplotlib.axis.plot.
        """
        indeps = list(indeps)
        # unnormalized_centers = net.centers[:,indeps]*net.input_scale[indeps]+net.input_shift[indeps]
        unnormalized_centers = self.denormalize_input(net.centers)[:,indeps]
        axis.plot(*unnormalized_centers.T, *args, 'x', **kwargs)

    def predict(self, input):
        """
        Make one or more predictions using the RBF net.

        Parameters
        ----------
        input: numpy.ndarray
            input[i,j] is prediction point i, independent variable j

        Returns
        -------
        numpy.ndarray where output[i] is the prediction of point i
        """
        # inp = (input-self.input_shift)/self.input_scale
        inp = self.normalize_input(input)

        output = np.zeros(inp.shape[0])
        for j in range(len(self.centers)):
            distance = np.linalg.norm(inp-self.centers[j,:], axis=1)
            output += self.coeffs[j]*self.rbf(distance/self.radius)

        # output = output*self.output_scale + self.output_shift
        output = self.denormalize_output(output)

        return output

    def normalize_input(self, input):
        norm_input = (input-self.input_shift)/self.input_scale
        return norm_input

    def normalize_output(self, output):
        norm_output = (output-self.output_shift)/self.output_scale
        return norm_output

    def denormalize_input(self, norm_input):
        input = norm_input*self.input_scale + self.input_shift
        return input

    def denormalize_output(self, norm_output):
        output = norm_output*self.output_scale + self.output_shift
        return output

    def save(self, fname):
        """
        Save trained model to file.

        Parameters
        ----------
        fname: string
            filename
        """
        # Radius
        # Centers
        # Normalization
        pass

    def load(self, fname):
        """
        Load a previously trained model from file.

        Parameters
        ----------
        fname: string
            filename
        """
        pass

N = 100
M = 9000
M2 = 10000
K = 20
data = read_RBF_data(sys.argv[1])
currents = data[:,0:4]
density = data[:,4]
temperature = data[:,5]
voltage = data[:,6]

training_set = (currents[:M], density[:M])
validation_set = (currents[M:M2], density[M:M2])

# training_set = (currents[:M], voltage[:M])
# validation_set = (currents[M:M2], voltage[M:M2])

# training_set = (currents[:M], temperature[:M])
# validation_set = (currents[M:M2], temperature[M:M2])

# centers = 50

# net = RBFnet()
# net.train(*training_set, centers=centers, radius=1.5, random_state=5)
# net.train(*training_set, centers=centers, random_state=5)

# pred = net.predict(training_set[0][:K])
# error = net.error(*validation_set)
# print("Relative validation error: ", error)

# input_shift = np.mean(training_set[0], axis=0)
# input_scale = np.std(training_set[0], axis=0)
# input = (training_set[0]-input_shift)/input_scale

# lower = np.min(input, axis=0)
# upper = np.max(input, axis=0)
# maxdist = max(upper-lower)
# dim = len(upper)
# radius_0 = maxdist/(centers**(1./dim))
# print('guess: ', radius_0)

# i = 0
# def f(radius):
#     net.train(*training_set, centers=centers, radius=radius, random_state=5, reuse=True)
#     global i
#     i = i + 1
#     err = net.error(*training_set)
#     print(i, radius[0], err)
#     return err

# radius_0 = 1
# res = minimize(f, radius_0, tol=0.00001, options={'maxiter':100, 'disp':True},
#                # method = 'powell')
#                method = 'nelder-mead')
# print(res.x)

net = RBFnet()

net.train(*training_set, radius=None, verbose=True, random_state=5, measure=mean_rel_error)
pred = net.predict(training_set[0])
npred = net.normalize_output(pred)
ntrue = net.normalize_output(training_set[1])

print(np.sqrt(net.residual/len(pred)))
print(rms_error(npred,ntrue))


plt.figure()
rs = np.logspace(-2, 3, 200)
ns = [5,10,20]#,50,100]
ns = [50]
for i, n in enumerate(tqdm(ns)):
    err = []
    net.adapt_normalization(*training_set)
    net.compute_centers(training_set[0], num=n, random_state=5)
    for r in tqdm(rs):
        net.fit_weights(*training_set, r)
        # err.append(net.error(*training_set))
        err.append(rms_error(training_set[1], net.predict(training_set[0])))
    plt.loglog(rs, err, 'C{}'.format(i))

# for i, n in enumerate(tqdm(ns)):
#     net = RBFnet()
#     net.train(*training_set, num=n, random_state=5)
#     plt.axvline(net.radius, color='C{}'.format(i))
plt.show()

# print(currents.shape)
# plot_data(currents, net)

# pred = net.predict(training_set[0][:K])
# # print_table(zip(pred, density[0:K], (pred-density[0:K])/density[0:K]))
# error = net.error(*validation_set)
# print("Relative validation error optimized: ", error)

# plot = plt.plot
# plt.figure()
# # plot(density[:M2:10], net.predict(currents[:M2:10]), '+', ms=3)
# # plot([1e11,12e11],[1e11,12e11], '-k', lw=0.8)
# plot(training_set[1], net.predict(training_set[0]), '+', ms=3)
# r = (min(training_set[1]), max(training_set[1]))
# plot(r,r,'-k',lw=0.8)
# plt.show()
