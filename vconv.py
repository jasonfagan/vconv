__author__ = 'Jason Fagan'

import os
import shutil
import sys
import re
import subprocess

import Queue
import threading
import time
import getopt

formats = [".mp4", ".ogv"]
ffmpeg = "/usr/local/bin/ffmpeg"
ffprobe = "/usr/local/bin/ffprobe"
output_dir = False
output_formats = ["flv", "mp4"]
output_format = output_formats[0]
processed_dir = False
qualities = [ "low", "medium", "high" ]
quality = qualities[0]
queue = Queue.Queue()
rejected_dir = False
rootdir = False
threads = 1
verbose = False

converter_configurations = {
    "flv": {
        "low": [
            "-f", "flv",
            #                   "-acodec", "aac",
            #                   "-scodec", "copy",
            #                   "-vcodec", "h264"
            "-ar", "22050",
            "-ab", "128k",
            "-b", "0.5m",
            "-s", "320x240"
        ],
        "medium": [
            "-f", "flv",
            "-ar", "44100",
            "-ab", "192k",
            "-b", "1m",
            #                       "-s", "480x360"
        ],
        "high": [
            "-f", "flv",
            "-ar", "44100",
            "-ab", "192k",
            "-b", "2m",
            "-s", "480x360"
        ]
    },
    'mp4': {
        "low": [
            "-f", "mp4",
            "-acodec", "aac",
            "-scodec", "copy",
            "-vcodec", "libx264",
            "-ar", "22050",
            "-ab", "96k",
            "-ac", "2",
            "-b:v", "0.5M",
            #                       "-vpre", "default",
            #                       "-vpre", "baseline"
            #                       "-s", "320x240"
        ]
    }
}

def get_converter_args(fmt, quality):
    return converter_configurations[fmt][quality]

common_args = [ "-strict", "-2",
    "-y"
]

#ffprobe -v quiet -print_format json -show_format -show_streams
#ffmpeg -re -i "%WMSAPP_HOME%/content/sample.mp4" -vcodec libx264 -vpre default -vpre baseline -g 60
# -vb 150000 -strict experimental
# -acodec aac -ab 96000 -ar 48000 -ac 2 -vbsf h264_mp4toannexb -f mpegts udp://127.0.0.1:10000?pkt_size=1316

#RTSP/RTP camera:
#ffmpeg -i "rtsp://192.168.1.22/mycamera" -vcodec libx264 -vpre default -vpre baseline -g 60 -vb 150000 -strict experimental -acodec aac -ab 96000 -ar 48000 -ac 2 -vbsf h264_mp4toannexb -f mpegts udp://127.0.0.1:10000?pkt_size=1316

#MPEG-TS stream:
#ffmpeg -i "udp://localhost:1234" -vcodec libx264 -vpre default -vpre baseline -g 60 -vb 150000 -strict experimental -acodec aac -ab 96000 -ar 48000 -ac 2 -vbsf h264_mp4toannexb -f mpegts udp://127.0.0.1:10000?pkt_size=1316

#Native RTP stream:
#ffmpeg -i "unicast.sdp" -vcodec libx264 -vpre default -vpre baseline -g 60 -vb 150000 -strict experimental -acodec aac -ab 96000 -ar 48000 -ac 2 -vbsf h264_mp4toannexb -f mpegts udp://127.0.0.1:10000?pkt_size=1316

class Converter:
    def __init__(self, file, fmt, quality):
        self.file = file
        self.fmt = fmt
        self.quality = quality
        self.input_file = os.path.join(rootdir, self.file)

    def info(self):
        args = [ffprobe,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                self.input_file]
        child = subprocess.Popen(args, stdin=open(os.devnull, 'rb'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        child.wait()
        if child.returncode:
            for line in child.stderr:
                print("stderr: " + line.rstrip())
        else:
            for line in child.stdout:
                print("stdout: " + line.rstrip())


    def convert(self):
        output_file = os.path.join(output_dir, "output", re.sub("(" + '|'.join(formats) + ")", "." + self.fmt, self.file))
        args = [ffmpeg, '-i', self.input_file]
        args += get_converter_args(self.fmt, self.quality)
        args += common_args
        args += [ output_file ]
        start = time.time()
        if verbose:
            sys.stdout.write("Processing file %s\n" % output_file)
        child = subprocess.Popen(args, stdin=open(os.devnull, 'rb'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        child.wait()
        elapsed = time.time() - start
        if verbose:
            sys.stdout.write("Generation of %s" % output_file)

        if child.returncode:
            if not shutil.move(self.input_file, os.path.join(rejected_dir, self.file)):
                sys.stderr.write("Failed to move %s to %s" % (self.input_file, rejected_dir))

            if verbose:
                sys.stdout.write(" ... Failed!\n")
#            for line in child.stdout:
#                print("stdout: " + line.rstrip())
                for line in child.stderr:
                    print("stderr: " + line.rstrip())
        else:
            if verbose:
                sys.stdout.write(" ... Complete in %.3f seconds\n" % elapsed)

            if not shutil.move(self.input_file, os.path.join(processed_dir, self.file)):
                sys.stderr.write("Failed to move %s to %s" % (self.input_file, processed_dir))


class ConverterThread(threading.Thread):
    def __init__(self, queue):
        threading.Thread.__init__(self)
        self.queue = queue

    def run(self):
        while True:
            converter = self.queue.get()
            converter.convert()
            self.queue.task_done()

def main():

    if not os.path.exists(rootdir):
        sys.stderr.write("Monitor directory %s not found" % rootdir)
        sys.exit(2)

    if not os.path.exists(output_dir):
        sys.stderr.write("Output directory %s not found" % output_dir)
        sys.exit(2)

    if not os.path.exists(processed_dir):
        sys.stderr.write("Processed directory %s not found" % processed_dir)
        sys.exit(2)

    if not os.path.exists(rejected_dir):
        sys.stderr.write("Rejected directory %s not found" % rejected_dir)
        sys.exit(2)

    print "Monitoring %s" % rootdir

    while(True):
        for i in range(threads):
            t = ConverterThread(queue)
            t.setDaemon(True)
            t.start()

        for file in os.listdir(rootdir):
            if file[-4:] in formats:
                queue.put(Converter(file, output_format, quality))

        queue.join()

        if verbose:
            print "Waiting for files"

        try:
            time.sleep(60)
        except KeyboardInterrupt:
            sys.stderr.write("CTRL+C, exiting...")
            sys.exit(0)

def usage():
    sys.stderr.write("vconv.py [-h | --help] [-d dir | --dir=dir] [-f fmt | --format=fmt] [-o dir | --output=dir] "
                     "[-p dir | --processed=dir} [-q value | --quality=value] [-r dir | --rejected=dir"
                     "[-t 1 | --threads=1] [-v | --verbose] [--ffmpeg=/path/ffmpeg] [--ffprobe /path/ffprobe]\n")
    sys.stderr.write("\n")
    sys.stderr.write("\t-d dir | --dir=dir             monitor directory (required)\n")
    sys.stderr.write("\t-h | --help                    shows this help\n")
    sys.stderr.write("\t-f fmt | --format=fmt          output format (choices: %s, default: %s)\n"
                     % (', '.join(output_formats), output_format))
    sys.stderr.write("\t-o dir | --output=dir          directory to place converted files (default: output)\n")
    sys.stderr.write("\t-p dir | --processed=dir       directory to place original videos after conversion "
                     "(default: processed)\n")
    sys.stderr.write("\t-q value | --quality=value     output quality (choices: %s, default: %s)\n"
                     % (', '.join(qualities), quality))
    sys.stderr.write("\t-r dir | --rejected=dir        directory to place original videos after failed conversion "
                     "(default: rejected)\n")
    sys.stderr.write("\t-t 1 | --threads=1             number of threads to process videos (default: %d)\n" % threads)
    sys.stderr.write("\t-v | --verbose                 verbose output\n")
    sys.stderr.write("\t--ffmpeg=/path/ffmpeg          path to ffmpeg program (default: %s)\n" % ffmpeg)
    sys.stderr.write("\t--ffprobe=/path/ffprobe        path to ffprobe program (default: %s)\n" % ffprobe)
    sys.stderr.write("\n")

try:
    options, remainder = getopt.gnu_getopt(sys.argv[1:], 'd:f:ho:p:q:r:t:v',
        ['dir=',
         'format=',
         'help',
         'output=',
         'processed=',
         'quality=',
         'rejecetd='
         'threads=',
         'verbose',
         'ffmpeg=',
         'ffprobe=',
        ])

except getopt.GetoptError:
    usage()
    sys.exit(2)

for opt, arg in options:
    if opt in ('-d', '--dir'):
        rootdir = arg
    elif opt in ('-f', '--format'):
        output_format = arg
    elif opt in ('-h', '--help'):
        usage()
        sys.exit(2)
    elif opt in ('-o', '--output'):
        output_dir = arg
    elif opt in ('-p', '--processed'):
        processed_dir = arg
    elif opt in ('-q', '--quality'):
        quality = arg
    elif opt in ('-r', '--rejected'):
        rejected_dir = arg
    elif opt in ('-t', '--threads'):
        threads = arg
    elif opt in ('-v', '--verbose'):
        verbose = True
    elif opt == '--ffmpeg':
        ffmpeg = arg
    elif opt == '--ffprobe':
        ffprobe = arg
    else:
        usage()
        sys.exit(2)

if not rootdir:
    sys.stderr.write("Error! No directory specified.\n")
    usage()
    sys.exit(2)

if not output_dir:
    output_dir = os.path.join(rootdir, "output")
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)


if not processed_dir:
    processed_dir = os.path.join(rootdir, "processed")
    if not os.path.exists(processed_dir):
        os.mkdir(processed_dir)

if not rejected_dir:
    rejected_dir = os.path.join(rootdir, "rejected")
    if not os.path.exists(rejected_dir):
        os.mkdir(rejected_dir)

if not output_format in converter_configurations.keys():
    sys.stderr.write("Unsupported format: %s, available formats: %s"
                     % (output_format, ', '.join(converter_configurations.keys())))
    sys.exit(2)

if not quality in converter_configurations[output_format].keys():
    sys.stderr.write("Unsupported quality: %s, available options: %s"
                     % (quality, ', '.join(converter_configurations[output_format].keys())))
    sys.exit(2)

main()