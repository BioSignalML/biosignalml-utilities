######################################################
#
#  BioSignalML Management in Python
#
#  Copyright (c) 2010-2013  David Brooks
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
######################################################

'''
The PDF file structure is documented in
https://wwwimages2.adobe.com/content/dam/Adobe/en/devnet/pdf/pdfs/pdf_reference_1-7.pdf,
with Appendix A providing a summary of operators. The main operators recognised by this
application are:

q
  Save graphics state
Q
  Restore graphics state

BT
  Begin text object
TJ
  Show text
ET
  End text object

cm
  Concatenate matrix to current transformation matrix
w
  Set line width
m
  Begin new subpath
l
  Append straight line segment to path

h
  Close subpath
S
  Stroke path

'''

import logging
import numpy as np

import pypdf

from biosignalml.data import Clock, TimeSeries
from biosignalml.formats.hdf5 import HDF5Recording


POINTS2MM = 25.4/72.0


class GraphicsMap(object):
#=========================

  def __init__(self, Sx=1, Sy=1, Tx=0, Ty=0):
  #------------------------------------------
    self._matrix = [Sx, Sy, Tx, Ty]

  def map(self, point):
  #--------------------
    return (float(self._matrix[0])*point[0] + self._matrix[2],
            float(self._matrix[1])*point[1] + self._matrix[3])


class ECG_PDF(object):
#=====================

  '''
  Extract ECG data from a PDF generated by the AliveCor app.

  Using ``{`` to represent ``Save graphics state`` and ``}`` to represent ``Restore
  graphics state``, ``[ description ]`` to describe sequences of other operators,
  ``(value)`` for variable operator parameters, ``#`` for comments, and ignoring
  irrelevant operators, the first page of an AliveCor PDF file has the structure: ::

    { # Stage 1
      }

    { # Stage 2
      [ Set colour rendering ]
      {
        [ Draw image `Im` ]
        }

      [ Set colour rendering ]
      {
        [ Draw text object ]
        } 
      # above block repeats 13 times

      /Pattern cs      # Use ``\\Pattern`` colourspace
      /P1 scn          # Use ``\\P1`` colour for fill
      [ Closed fill of pattern ]

      0.4 w
      [ Single closed line of plot area border ]

      [ Multiple lines of horizontal grid for beat markers ]

      0.3 w
      [ Multiple lines of vertical grid ]

      0.3 G
      [ Multiple lines of horizontal grid for traces ]

      0 g
      {
        [ Draw text object ]
        } 
      }


    { # Stage 3
      1.5 w
      [ Single line of calibration pulse ]

      0.4 w
      [ Single line of trace ]
      0.6 w
      [ Beat markers ]
      # above repeats for each trace

  ``[ Beat markers ]`` consist of: ::

    {
      [ Single line of beat marker ]
      }
    # above block repeated for each marker

  ``A [ Single line of ... ]`` consists of: ::

    {
      1 0 0 -1 (Tx) (Ty) cm
      (X0) (Y0) m
      (X1) (Y1) l
      # Repeated line segments...
      (Xn) (Yn) l
      S
      }

  ``A [ Single closed line of ... ]`` consists of: ::

    {
      1 0 0 -1 (Tx) (Ty) cm
      (X0) (Y0) m
      (X1) (Y1) l
      # Repeated line segments...
      (Xn) (Yn) l
      h S
      }

  ``[ Multiple lines of ... ]`` consists of: ::

    {
      1 0 0 -1 (Tx) (Ty) cm
      (X0) (Y0) m (X1) (Y1) l
      # Above repeated...
      S
      }

  ``[ Closed fill of pattern ]`` consists of: ::

    (X0) (Y0) m
    (X1) (Y1) l
    # Repeated line segments...
    (Xn) (Yn) l
    h f

  '''
  def __init__(self, pdf_file):
  #----------------------------
    self._reader = pypdf.PdfReader(pdf_file)
    self._page = self._reader.pages[0]
    self._bounds = [0.0, 0.0,  0.0, 0.0]   # x, y, w, h
    self._text = [ ]
    self._ecg = None
    self._beats = None
    self._scan(self._page.get_contents().get_data().decode('utf-8'))


  def _scan(self, data):
  #---------------------
    stage = 0
    level = 0
    intext = False
    params = [ ]
    transform = GraphicsMap()
    graphicstate = [ ]
    linestate = 0
    X_min = None
    X_max = None
    T_width = None
    t_start = None
    subtrace = -1
    origins_trace = [ ]
    origins_beats = [ ]
    times = [ ]
    trace = [ ]
    beats = [ ]
    T_scale = 25.0   # mm/s
    V_scale = 10.0   # mm/mV

    for d in data.split():
      v = None
      try: v = int(d)
      except ValueError:
        try: v = float(d)
        except ValueError: pass
      if v is not None:
        params.append(v)
        continue

      if   d == 'q':
        graphicstate.append(transform)
        transform = GraphicsMap()
        if level == 0: stage += 1
        level += 1

      elif d == 'Q':
        transform = graphicstate.pop()
        if linestate: linestate += 1
        level -= 1

      elif d == 'BT':
        intext = True

      elif d == 'ET':
        intext = False

      elif d == 'cm':
        assert(len(params) == 6 and params[1:3] == [0, 0])
        transform = GraphicsMap(params[0], params[3], params[4], params[5])

      elif d == 'w':
        assert(len(params) == 1)
        w = params[0]
        if   stage == 2:
          if   w == 0.4:  # Plot border followed by beat marker grid
            linestate = 1
          elif w == 0.3:  # Vertical grid followed by trace grid
            linestate = 11
        elif stage == 3:
          if   w == 1.5:  # Calibration pulse
            # 1mV for 0.2s
            linestate = 21
          elif w == 0.4:  # Trace
            subtrace += 1
            linestate = 22
          elif w == 0.6:  # Beat marker
            linestate = 23

      elif d == 'm':
        assert(len(params) == 2)
        (x, y) = transform.map(params)
        if   linestate == 1:   # Border
          X_min = x
        elif linestate == 2:   # Beat grid
          origins_beats.append(y)
        elif linestate == 12:  # Trace grid
          origins_trace.append(y)
        elif linestate == 22:  # In trace
          if t_start is None:
            t_start = x
            times.append(0.0)
          else:
            t_start -= T_width
            times.append(x - t_start)
          trace.append(y - origins_trace[subtrace])
        elif linestate >= 23:  # Beat markers
          beats.append(x - t_start)

      elif d == 'l':
        assert(len(params) == 2)
        (x, y) = transform.map(params)
        if   linestate == 1:   # Border
          if T_width is None:
            X_max = x
            T_width = X_max - X_min
        elif linestate == 22:  # In trace
          times.append(x - t_start)
          trace.append(y - origins_trace[subtrace])

      params = [ ]

    self.ecg = (np.array(times), np.array(trace))
    self.ecg[0].__imul__(POINTS2MM/T_scale)
    self.ecg[1].__imul__(POINTS2MM/V_scale)

    self.beats = np.array(beats)
    self.beats.__imul__(POINTS2MM/T_scale)

"""
BT    Begin text
(text) TJ
[ (text1) M1 (text2) M2 (text3) ] TJ   # M1 etc are floats
ET    End text
"""


if __name__ == '__main__':
#-------------------------

  import sys, os
  import math

  from biosignalml.units import UNITS


  logging.basicConfig(format='%(asctime)s: %(message)s')
  logging.getLogger().setLevel('DEBUG')

  if len(sys.argv) < 2:
    print("Usage: %s ALIVECOR_PDF_FILE" % sys.argv[0])
    sys.exit(1)

  pdf = ECG_PDF(sys.argv[1])

#  import matplotlib.pyplot as plt
#  plt.plot(pdf.ecg.times, pdf.ecg.data)
#  plt.plot(pdf.beats, -0.5*np.ones(len(pdf.beats)),
#           linestyle='None', marker='|', color='magenta')
#  plt.show()

  repository = 'http://demo.biosignalml.org'
  basename = os.path.splitext(sys.argv[1])[0]
#  uri = 'file://' + os.path.abspath(basename)
  uri = repository + '/AliveCor/' + basename
  hdf5 = HDF5Recording.create(uri, basename + '.bsml', replace=True)
  hdf5.duration = math.ceil(pdf.ecg[0][-1])

  ecgtimes = Clock(uri + '/ecgclock', pdf.ecg[0], units='seconds', label='ECG clock')
  s = hdf5.new_signal(uri + '/ecg', 'mV', clock=ecgtimes, label='ECG')
  s.extend(pdf.ecg[1])

  beats = Clock(uri + '/beatclock', pdf.beats, units='seconds', label='Beat times')
  b = hdf5.new_signal(uri + '/beats', UNITS.AnnotationData, clock=beats, label='Beats')
  b.extend(np.ones(len(pdf.beats)))
  for n, t in enumerate(pdf.beats):
    b_uri = uri + '/beat/%d' % n
    hdf5.new_event(b_uri, 'http://biosignalml.org/AliveCor#beat', t,
                   label = 'Beat %d' % n)
  hdf5.close()


  #beat_uri = uri + '/beats'
  #hdf5.create_clock(beat_uri, units='seconds', times=pdf.beats)



  """
    hdf5.create_clock(annclock, dtype='i8', scale=1.0/framerate)
    anntimes = np.zeros(SIGBUFSIZE,     'i8')
    anndata = np.zeros((SIGBUFSIZE, 4), 'i1')
    events = '%s/signal/%s' % (uri, ann)
    hdf5.create_signal(events, ANNOTATOR_BASE + ann, dtype='i1', shape=(4,), clock=annclock)


    pos = 0
    anninfo = wfdb.WFDB_Anninfo()
    anninfo.name = ann
    anninfo.stat = wfdb.WFDB_READ
    if wfdb.annopen(record, anninfo, 1) < 0:
      raise IOError("Cannot open annotation '%s' for %s" % (ann, record))


    wfdb.iannsettime(0)
    annot = wfdb.WFDB_Annotation()


    while wfdb.getann(0, annot) == 0:
      anntimes[pos] = annot.time
      anndata[pos, 0] = annot.anntyp
      anndata[pos, 1] = annot.subtyp
      anndata[pos, 2] = annot.chan
      anndata[pos, 3] = annot.num
      pos += 1
      if pos >= SIGBUFSIZE:
        hdf5.extend_clock(annclock, anntimes)
        hdf5.extend_signal(events,  anndata)
        pos = 0
    if pos > 0:
      hdf5.extend_clock(annclock, anntimes[:pos])
      hdf5.extend_signal(events,  anndata[:pos])

    turtle = rec.metadata_as_string(base=baseuri, format=rdf.Format.TURTLE)
    h5.store_metadata(turtle, rdf.Format.TURTLE)

  """
