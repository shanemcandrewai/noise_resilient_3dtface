""" Replication toolkit """
from pathlib import Path
import shutil
import urllib.request
import bz2
import subprocess as sp
import warnings
import matplotlib.pyplot as plt
import numpy as np
from scipy.spatial import procrustes
from scipy import stats
import dlib

class Frames:
    """ Frame file manager """
    def __init__(self, frames_dir=None, video=None, suffix='.jpeg', num_len=4):
        if frames_dir is None:
            self.frames_dir = Path('..', 'replic', 'frames')
        else:
            self.frames_dir = Path(frames_dir)
        if video is None:
            self.video = Path('..', 'replic', 'samples', 'obama2s.mp4')
        else:
            self.video = Path(video)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.suffix = suffix
        self.num_len = num_len

    def get_file_path(self, frame_num=30):
        """ Build file path from frame number """
        return Path(self.frames_dir, str(frame_num).zfill(
            self.num_len)).with_suffix(self.suffix)

    def get_frame_file_names(self):
        """ Get list of frame files """
        return sorted(self.frames_dir.glob('*' + self.suffix))

    def get_frame_nums(self):
        """ Get list of frame numbers """
        frames = self.get_frame_file_names()
        return [int(Path(frame).stem) for frame in frames]

class DlibProcess:
    """ Dlib facial landmark extraction manager """
    def __init__(self, model_dir=None,
                 model_url='https://raw.github.com/davisking/dlib-models/master/'
                           'shape_predictor_68_face_landmarks.dat.bz2'):
        if model_dir is None:
            self.model_file = Path(Path('..', 'data'), Path(model_url).stem)
        else:
            self.model_file = Path(model_dir, Path(model_url).stem)
        self.detector = dlib.get_frontal_face_detector()
        self.rgb_image = None
        self.frame_num = None
        self.faces = None
        self.shape = None
        if not self.model_file.is_file():
            print('Model ' + str(self.model_file) + ' not found')
            print('Downloading from ' + model_url)
            with urllib.request.urlopen(model_url) as response, open(
                    self.model_file, 'wb') as model:
                model.write(bz2.decompress(response.read()))
        self.predictor = dlib.shape_predictor(str(self.model_file))

    def load_image(self, frame_num=30, frames=None):
        """ load image and attempt to extract faces """
        if frames is None:
            image_file_path = Frames().get_file_path(frame_num)
        else:
            image_file_path = frames.get_file_path(frame_num)
        self.faces = None
        self.shape = None
        self.rgb_image = dlib.load_rgb_image(str(image_file_path))
        if self.rgb_image is not None:
            self.frame_num = frame_num
            print('Frame ', frame_num, ' extracting faces')
            self.faces = self.detector(self.rgb_image, 1)

    def get_shape(self, frame_num=30):
        """ Retrieve or extract landmarks from face as dlib.points """
        if self.shape is None or frame_num != self.frame_num:
            self.extract_shape(frame_num)
        return self.shape

    def extract_shape(self, frame_num=30):
        """ Extract landmarks from face as dlib.points """
        if self.faces is None or frame_num != self.frame_num:
            self.load_image(frame_num)
        if len(self.faces) > 0:
            print('Frame ', frame_num, ' face ', 0, ' extracting landmarks')
            self.shape = self.predictor(self.rgb_image, self.faces[0])

    def get_lmarks(self, frame_num=30):
        """ Get landmarks from face as ndarray """
        if self.get_shape(frame_num) is None:
            return np.full((1, 68, 2), np.nan)
        return np.array([(part.x, part.y) for part in self.shape.parts()]).reshape((1, 68, 2))

    def display_overlay(self, frame_num=30):
        """ Display image overlayed with landmarks """
        win = dlib.image_window()
        win.clear_overlay()
        self.load_image(frame_num)
        win.set_image(self.rgb_image)
        if self.get_shape(frame_num) is not None:
            win.add_overlay(self.shape)
        dlib.hit_enter_to_continue()

class DataProcess:
    """ Calculations and supporting methods required for the replication of experiments """
    def __init__(self, data_dir=None, extract_file=None, frames=None):
        if data_dir is None:
            self.data_dir = Path('..', 'replic', 'data')
        else:
            self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if extract_file is None:
            self.extract_file = 'obama2s.npy'
        else:
            self.extract_file = Path(extract_file)
        if frames is None:
            self.frames = Frames()
        else:
            self.frames = frames
        self.axes = None
        self.all_lmarks = np.empty((0, 68, 2))

    def get_all_lmarks(self, new_extract=False, dlib_proc=None):
        """ Get landmarks from face for all frames as ndarray """
        if dlib_proc is None:
            dlib_proc = DlibProcess()
        extract = Path(self.data_dir, self.extract_file)
        if new_extract:
            self.all_lmarks = None
        elif extract.is_file():
            self.all_lmarks = np.load(extract)
        if self.all_lmarks.size == 0:
            if not self.frames.get_frame_nums():
                Video().extract_frames(self.extract_file.with_suffix('.mp4'))
            for frame_num in self.frames.get_frame_nums():
                self.all_lmarks = np.concatenate([self.all_lmarks,
                                                  dlib_proc.get_lmarks(frame_num)])
            np.save(extract, self.all_lmarks)
        return self.all_lmarks

    def get_procrustes(self, lmarks=None, lips_only=False):
        """ Procrustes analysis - return landmarks best fit to mean landmarks """
        if lmarks is None:
            lmarks = self.get_all_lmarks()
        if lips_only:
            lmarks = lmarks[:, 48:, :]
        mean_lmarks = np.nanmean(lmarks, 0, keepdims=True)
        proc_lmarks = np.full(lmarks.shape, np.nan)
        for frame_num in range(lmarks.shape[0]):
            if ~np.isnan(lmarks[frame_num, 0, 0]):
                _, proc_lmarks[frame_num], _ = procrustes(
                    mean_lmarks[0], lmarks[frame_num])
        if lips_only:
            not_lips = np.full((proc_lmarks.shape[0], proc_lmarks.shape[1],
                                48, proc_lmarks.shape[3]), np.nan)
            proc_lmarks = np.concatenate((not_lips, proc_lmarks), 2)
        return proc_lmarks

    def interpolate_lmarks(self, lmarks=None, old_rate=30, new_rate=25):
        """ Change the frame rate of the extracted landmarks using linear
            interpolation """
        if lmarks is None:
            lmarks = self.get_procrustes()
        old_frame_axis = np.arange(lmarks.shape[0])
        new_frame_axis = np.linspace(0, lmarks.shape[0]-1, int(
            lmarks.shape[0]*new_rate/old_rate))
        new_lmarks = np.zeros((len(new_frame_axis),) + (lmarks.shape[1:]))
        for ax1 in range(lmarks.shape[1]):
            for ax2 in range(lmarks.shape[2]):
                new_lmarks[:, ax1, ax2] = np.interp(new_frame_axis, old_frame_axis,
                                                    lmarks[:, ax1, ax2])
        return new_lmarks

    def get_closed_mouth_frame(self, lmarks=None, zscore=1.3):
        """ Determine frame with the minimum distance between the inner lips
            excluding frames where the mouth is unusually wide or narrow """
        if lmarks is None:
            lmarks = self.get_procrustes()
        lip_r = 60
        lip_l = 64
        mouth_width = np.linalg.norm(lmarks[:, lip_r] - lmarks[:, lip_l], axis=1)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', category=RuntimeWarning)
            lmarks_filtered = np.nonzero(np.abs(stats.zscore(
                mouth_width, nan_policy='omit')) < zscore)
        lip_top = slice(61, 64)
        lip_bottom = slice(65, 68)
        lip_dist = np.linalg.norm(lmarks[lmarks_filtered, lip_top] - lmarks[
            lmarks_filtered, lip_bottom], axis=2)
        return lmarks_filtered[0][np.argmin(np.sum(lip_dist, -1)[0])]

    def remove_identity(self, lmarks=None, template=None, file_out=None, zscore=0.1):
        """ current frame - the closed mouth frame + template """
        if lmarks is None:
            lmarks = self.get_procrustes()
        if template is None:
            template = Path('..', 'data', 'mean.npy')
        lmarks = self.interpolate_lmarks().reshape((-1, 68, 2))
        closed_mouth = lmarks[self.get_closed_mouth_frame(lmarks=lmarks, zscore=zscore)]
        template_2d = np.load(str(template))[:, :2]
        identity_removed = lmarks - closed_mouth + template_2d
        if file_out is not None:
            Path(self.data_dir, file_out).parent.mkdir(parents=True, exist_ok=True)
            np.save(Path(self.data_dir, file_out), identity_removed)
        return identity_removed

class Draw:
    """ Draw landmarks with matplotlib """
    def __init__(self, plots_dir=None, data_proc=None, dimensions=None):
        if plots_dir is None:
            self.plots_dir = Path('..', 'replic', 'plots')
        else:
            self.plots_dir = Path(plots_dir)
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        if data_proc is None:
            self.data_proc = DataProcess()
        else:
            self.data_proc = data_proc
        if dimensions is None:
            self.dimensions = {'width': 500, 'height': 500}
        else:
            self.dimensions = dimensions
        lmarks = self.data_proc.get_all_lmarks()
        self.axes = None
        self.bounds = {'mid': np.nanmean(lmarks, 0),
                       'xmid': np.nanmean(lmarks[..., 0]),
                       'ymid': np.nanmean(lmarks[..., 1])}

    def _plot_features(self, lmarks, frame_num=0):
        """ calculate and plot facial features """
        features = {'jaw': lmarks[frame_num, :17],
                    'eyebrow_r': lmarks[frame_num, 17:22],
                    'eyebrow_l': lmarks[frame_num, 22:27],
                    'nose_top': lmarks[frame_num, 27:31],
                    'nose_side_r': np.concatenate((lmarks[frame_num, 27:28],
                                                   lmarks[frame_num, 31:32])),
                    'nose_side_l': np.concatenate((lmarks[frame_num, 27:28],
                                                   lmarks[frame_num, 35:36])),
                    'nose_mid_r': lmarks[frame_num, 30:32],
                    'nose_mid_l': np.concatenate((lmarks[frame_num, 30:31],
                                                  lmarks[frame_num, 35:36])),
                    'nose_bottom': lmarks[frame_num, 31:36],
                    'eye_r': np.concatenate((lmarks[frame_num, 36:42],
                                             lmarks[frame_num, 36:37])),
                    'eye_l': np.concatenate((lmarks[frame_num, 42:48],
                                             lmarks[frame_num, 42:43])),
                    'lips_out': np.concatenate((lmarks[frame_num, 48:60],
                                                lmarks[frame_num, 48:49])),
                    'lips_in': np.concatenate((lmarks[frame_num, 60:],
                                               lmarks[frame_num, 60:61]))}

        self.axes.plot(features['jaw'][:, 0], features['jaw'][:, 1], 'b-')
        self.axes.plot(features['eyebrow_r'][:, 0], features['eyebrow_r'][:, 1], 'b-')
        self.axes.plot(features['eyebrow_l'][:, 0], features['eyebrow_l'][:, 1], 'b-')
        self.axes.plot(features['nose_top'][:, 0], features['nose_top'][:, 1], 'b-')
        self.axes.plot(features['nose_side_r'][:, 0], features['nose_side_r'][:, 1], 'b-')
        self.axes.plot(features['nose_side_l'][:, 0], features['nose_side_l'][:, 1], 'b-')
        self.axes.plot(features['nose_mid_r'][:, 0], features['nose_mid_r'][:, 1], 'b-')
        self.axes.plot(features['nose_mid_l'][:, 0], features['nose_mid_l'][:, 1], 'b-')
        self.axes.plot(features['nose_bottom'][:, 0], features['nose_bottom'][:, 1], 'b-')
        self.axes.plot(features['eye_r'][:, 0], features['eye_r'][:, 1], 'b-')
        self.axes.plot(features['eye_l'][:, 0], features['eye_l'][:, 1], 'b-')
        self.axes.plot(features['lips_out'][:, 0], features['lips_out'][:, 1], 'b-')
        self.axes.plot(features['lips_in'][:, 0], features['lips_in'][:, 1], 'b-')

    def save_scatter(self, frame_num_sel=None, with_frame=True, dpi=96,
                     annot=False):
        """ Plot landmarks and save """
        _, self.axes = plt.subplots(figsize=(self.dimensions['width']/dpi,
                                             self.dimensions['height']/dpi), dpi=dpi)
        lmarks = self.data_proc.get_all_lmarks()
        if frame_num_sel is None:
            for frame_num in range(lmarks.shape[0]):
                self.save_scatter_frame(frame_num, lmarks, with_frame, annot=annot)
        else:
            self.save_scatter_frame(frame_num_sel, with_frame=with_frame,
                                    annot=annot)

    def save_scatter_frame(self, frame_num=30, lmarks=None, with_frame=True,
                           annot=False):
        """ Plot landmarks and save frame """
        self.axes.clear()
        if lmarks is None:
            lmarks = self.data_proc.get_all_lmarks()
        if with_frame:
            image = plt.imread(self.data_proc.frames.get_file_path(frame_num))
            self.axes.imshow(image)
        frame_left = self.bounds['xmid'] - self.dimensions['width']/2
        frame_right = self.bounds['xmid'] + self.dimensions['width']/2
        frame_bottom = self.bounds['ymid'] - self.dimensions['height']/2
        frame_top = self.bounds['ymid'] + self.dimensions['height']/2
        self.axes.set_xlim(frame_left, frame_right)
        self.axes.set_ylim(frame_bottom, frame_top)
        self.axes.invert_yaxis()
        self.axes.scatter(lmarks[frame_num, :, 0],
                          lmarks[frame_num, :, 1], marker='.')
        if annot:
            self.axes.annotate('Frame: ' + str(frame_num), xy=(
                frame_left + 10, frame_top - 10), color='cyan')
            for lmark_num, (point_x, point_y) in enumerate(
                    lmarks[frame_num]):
                self.axes.annotate(str(lmark_num+1), xy=(point_x, point_y))
        plt.savefig(Path(self.plots_dir, str(frame_num) + '.png'))

    def save_plots(self, lmarks=None, with_frame=True, annot=False, dpi=96):
        """ save line plots """
        _, self.axes = plt.subplots(figsize=(self.dimensions['width']/dpi,
                                             self.dimensions['height']/dpi), dpi=dpi)
        if lmarks is None:
            lmarks = self.data_proc.get_all_lmarks()
        if self.plots_dir.is_dir():
            shutil.rmtree(self.plots_dir)
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        for frame_num in range(lmarks.shape[0]):
            self.axes.clear()
            if with_frame:
                image = plt.imread(self.data_proc.frames.get_file_path(frame_num))
                self.axes.imshow(image)

            self._plot_features(lmarks, frame_num)
            self.axes.set_xlim(self.bounds['xmid'] - (self.dimensions['width']/2),
                               self.bounds['xmid'] + (self.dimensions['width']/2))
            self.axes.set_ylim(self.bounds['ymid'] - (self.dimensions['height']/2),
                               self.bounds['ymid'] + (self.dimensions['height']/2))
            self.axes.invert_yaxis()
            if annot:
                self.annotate(frame_num, lmarks)
            plt.savefig(Path(self.plots_dir, str(frame_num).zfill(
                self.data_proc.frames.num_len) + '.png'))

    def annotate(self, frame_num, lmarks):
        """ Annote image with landmark and frame numbers """
        self.axes.annotate('Frame: ' + str(frame_num), xy=(
            self.axes.get_xlim()[0] + 0.01, self.axes.get_ylim(
                )[0] - 0.01), color='blue')
        for lmark_num, (point_x, point_y) in enumerate(
                lmarks[frame_num]):
            self.axes.annotate(str(lmark_num+1), xy=(point_x, point_y))

    def save_plots_proc(self, dpi=96, annot=False, lips_only=False):
        """ save line plots with Procrustes analysis """
        _, self.axes = plt.subplots(figsize=(
            self.dimensions['width']/dpi, self.dimensions['height']/dpi), dpi=dpi)
        lmarks = self.data_proc.get_procrustes(lips_only=lips_only)
        if self.plots_dir.is_dir():
            shutil.rmtree(self.plots_dir)
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        for frame_num in range(lmarks.shape[0]):
            self.axes.clear()
            self.axes.set_aspect(1)
            self._plot_features(lmarks, frame_num)
            self.axes.invert_yaxis()
            if annot:
                self.annotate(frame_num, lmarks)
            plt.savefig(Path(self.plots_dir, str(frame_num).zfill(
                self.data_proc.frames.num_len) + '.png'))

class Video:
    """ FFmpeg video processing manager """
    def __init__(self, video_dir=None, audio_dir=None, frames=None):
        if video_dir is None:
            self.video_dir = Path('..', 'replic', 'video')
        else:
            self.video_dir = Path(video_dir)
        if audio_dir is None:
            self.audio_dir = Path('..', 'replic', 'audio')
        else:
            self.audio_dir = Path(audio_dir)
        if frames is None:
            self.frames = Frames()
        else:
            self.frames = frames

    def extract_audio(self, video_in='obama2s.mp4',
                      audio_out=None):
        """ Extract audio from video sample """
        if audio_out is None:
            audio_out = Path(self.audio_dir, Path(video_in).with_suffix('.wav'))
        Path(self.audio_dir).mkdir(parents=True, exist_ok=True)
        sp.run(['ffmpeg', '-i', str(Path(self.video_dir, video_in)), '-y',
                str(audio_out)], check=True)

    def extract_frames(self, video_in='obama2s.mp4', start_number=0, quality=5):
        """ Extract frames from video using FFmpeg """
        frame_dir = Path(self.frames.frames_dir)
        if frame_dir.is_dir():
            shutil.rmtree(frame_dir)
        frame_dir.mkdir(parents=True, exist_ok=True)
        sp.run(['ffmpeg', '-i', str(Path(self.video_dir, video_in)),
                '-start_number', str(start_number), '-qscale:v', str(quality),
                str(Path(frame_dir, r'%0' + str(
                    self.frames.num_len) + 'd' + self.frames.suffix))], check=True)

    def create_video(self, video_out='plots.mp4', plots_dir=None, framerate=25,
                     frame_text='frame %{frame_num} %{pts}'):
        """ create video from images """
        Path(self.video_dir, video_out).parent.mkdir(parents=True, exist_ok=True)
        if plots_dir is None:
            plots_dir = Path('..', 'replic', 'plots')
        sp.run(['ffmpeg', '-y', '-f', 'image2', '-framerate', str(framerate), '-i',
                str(Path(plots_dir, r'%0' + str(self.frames.num_len) + 'd.png')), '-vf',
                'drawtext=text=\'' + frame_text + '\':fontsize=20:x=10:y=10',
                str(Path(self.video_dir, video_out))], check=True)

    def stack_h(self, video_left='obama2s/obama2s_painted_t.mp4',
                video_right='identity_removed/obama2s.ir_painted_t.mp4',
                video_out=None):
        """ stack videos horizontally """
        if video_out is None:
            video_out = Path(Path(video_left).stem + '_compare.mp4')
        sp.run(['ffmpeg', '-i', str(Path(self.video_dir, video_left)), '-i',
                str(Path(self.video_dir, video_right)), '-filter_complex',
                'hstack=inputs=2', '-y',
                str(Path(self.video_dir, video_out))], check=True)

    def stack_v(self, video_top, video_bottom, video_out=None):
        """ stack videos vertically """
        if video_out is None:
            video_out = Path(Path(video_top).stem + '_v.mp4')
        Path(self.video_dir, video_out).parent.mkdir(parents=True, exist_ok=True)
        sp.run(['ffmpeg', '-i', Path(self.video_dir, video_top), '-i',
                Path(self.video_dir, video_bottom), '-filter_complex',
                'vstack=inputs=2', '-y',
                Path(self.video_dir, video_out)], check=True)

    def draw_text(self, video_in='obama2s_painted_.mp4', video_out=None,
                  frame_text='frame %{frame_num} %{pts}'):
        """ add text to video frames """
        if video_out is None:
            video_out = Path(Path(video_in).parent, Path(
                Path(video_in).stem + 't.mp4'))
        Path(self.video_dir, video_out).parent.mkdir(parents=True, exist_ok=True)
        sp.run(['ffmpeg', '-y', '-i', str(Path(self.video_dir, video_in)), '-vf',
                'drawtext=text=\'' + frame_text + '\':fontsize=20:x=10:y=10',
                str(Path(self.video_dir, video_out))], check=True)

    def prepare_ground_truth(self, video_in='080815_WeeklyAddress.mp4', video_out=None,
                             frame_text='frame %{frame_num} %{pts}'):
        """ add text to video frames """
        sp.run(['ffmpeg', '-y', '-i', str(Path(self.video_dir, video_in)), '-r', str(25),
                str(Path(self.video_dir, 'temp.mp4'))], check=True)
        if video_out is None:
            video_out = Path(Path(video_in).parent, Path(
                Path(video_in).stem + '_25t.mp4'))
        Path(self.video_dir, video_out).parent.mkdir(parents=True, exist_ok=True)
        sp.run(['ffmpeg', '-y', '-i', str(Path(self.video_dir, 'temp.mp4')), '-vf',
                'drawtext=text=\'' + frame_text + '\':fontsize=20:x=660:y=260,crop=500:500:650:250',
                str(Path(self.video_dir, video_out))], check=True)

    def prepare_anims(self, video_in='080815_WeeklyAddress_painted_.mp4', video_out=None,
                      frame_text='frame %{frame_num} %{pts}'):
        """ add text to video frames """
        if video_out is None:
            video_out = Path(Path(video_in).parent, Path(
                Path(video_in).stem + 't.mp4'))
        Path(self.video_dir, video_out).parent.mkdir(parents=True, exist_ok=True)
        sp.run(['ffmpeg', '-y', '-i', str(Path(self.video_dir, video_in)), '-vf',
                'scale=500:500,drawtext=text=\'' + frame_text + '\':fontsize=20:x=10:y=10',
                str(Path(self.video_dir, video_out))], check=True)
