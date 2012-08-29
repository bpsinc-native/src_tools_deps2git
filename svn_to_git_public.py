#!/usr/bin/python
# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""SVN to GIT mapping for the public Chromium repositories."""

import re


GIT_HOST = 'http://git.chromium.org/'


# Used by deps2git.ConvertDepsToGit() as overrides for SVN DEPS.  Each entry
# maps a DEPS path to a DEPS variable identifying the Git hash for its
# respective repository.  Variables are automatically transferred from SVN DEPS
# to .DEPS.git and converted into variables by deps_utils.Varify().
DEPS_OVERRIDES = {
  'src/third_party/ffmpeg': 'ffmpeg_hash'
}


def SvnUrlToGitUrl(path, svn_url):
  """Convert a chromium SVN URL to a chromium Git URL."""

  match = re.match('http://src.chromium.org/svn(/.*)', svn_url)
  if match:
    svn_url = match.group(1)

  # A few special cases.
  if svn_url == '/trunk/deps/page_cycler/acid3':
    return (path, GIT_HOST + 'chromium/deps/acid3.git')

  if svn_url == '/trunk/deps/canvas_bench':
    return (path, GIT_HOST + 'chromium/canvas_bench.git')

  if svn_url == '/trunk/deps/gpu/software_rendering_list':
    return (path, GIT_HOST + 'chromium/deps/gpu/software_rendering_list.git')

  if svn_url == '/trunk/tools/third_party/python_26':
    return (path, GIT_HOST + 'chromium/deps/python_26.git')

  if svn_url == '/trunk/deps/support':
    return (path, GIT_HOST + 'chromium/support.git')

  if svn_url == '/trunk/deps/frame_rate/content':
    return (path, GIT_HOST + 'chromium/frame_rate/content.git')

  if svn_url == 'svn://svn.chromium.org/jsoncpp/trunk/jsoncpp':
    return (path, GIT_HOST + 'external/jsoncpp/jsoncpp.git')

  if svn_url == '/trunk/deps/third_party/ffmpeg':
    return (path, GIT_HOST + 'chromium/third_party/ffmpeg.git')

  if svn_url == 'http://webrtc.googlecode.com/svn/stable/src':
    return (path, GIT_HOST + 'external/webrtc/stable/src.git')

  if svn_url in ('http://selenium.googlecode.com/svn/trunk/py/test',
                 '/trunk/deps/reference_builds/chrome'):
    # Those can't be git svn cloned. Skipping for now.
    return (None, None)

  # Projects on sourceforge using trunk
  match = re.match('http?://(.*).svn.sourceforge.net/svnroot/(.*)/trunk(.*)',
                   svn_url)
  if match:
    repo = '%s%s.git' % (match.group(2), match.group(3))
    return (path, GIT_HOST + 'external/%s' % repo)

  # Projects on googlecode.com using trunk.
  match = re.match('http?://(.*).googlecode.com/svn/trunk(.*)', svn_url)
  if match:
    repo = '%s%s.git' % (match.group(1), match.group(2))
    return (path, GIT_HOST + 'external/%s' % repo)

  # Projects on googlecode.com usng branches.
  match = re.match('http://(.*).googlecode.com/svn/branches/(.*)', svn_url)
  if match:
    repo = '%s/%s.git' % (match.group(1), match.group(2))
    return (path, GIT_HOST + 'external/%s' % repo)

  # Projects that are subdirectories of the native_client repository.
  match = re.match('http://src.chromium.org/native_client/trunk/(.*)', svn_url)
  if match:
    repo = '%s.git' % match.group(1)
    return (path, GIT_HOST + 'native_client/%s' % repo)

  # Projects that are subdirectories of the chromium/{src,tools} repository.
  match = re.match('/trunk/((src|tools)/.*)', svn_url)
  if match:
    repo = '%s.git' % match.group(1)
    return (path, GIT_HOST + 'chromium/%s' % repo)

  # Main webkit directory.
  if svn_url == 'http://svn.webkit.org/repository/webkit/trunk/Source':
    return ('src/third_party/WebKit',
            GIT_HOST + 'external/WebKit_trimmed.git')

  # Minimal header-only webkit directories for iOS.
  if svn_url == ('http://svn.webkit.org/repository/webkit/trunk/Source/' +
                 'WebKit/chromium/public'):
    return (path,
            GIT_HOST + 'external/WebKit/Source/WebKit/chromium/public.git')
  if svn_url == ('http://svn.webkit.org/repository/webkit/trunk/Source/' +
                 'Platform/chromium/public'):
    return (path,
            GIT_HOST + 'external/WebKit/Source/Platform/chromium/public.git')

  # Ignore all webkit directories (other than the above), since we fetch the
  # whole thing directly for all but iOS.
  if svn_url == '/trunk/deps/third_party/WebKit':
    return (None, None)

  if svn_url.startswith('http://svn.webkit.org'):
    return (None, None)

  # Subdirectories of the chromium deps/third_party directory.
  match = re.match('/trunk/deps/third_party/(.*)', svn_url)
  if match:
    repo = '%s.git' % match.group(1)
    return (path, GIT_HOST + 'chromium/deps/%s' % repo)

  # Subdirectories of the chromium deps/reference_builds directory.
  match = re.match('/trunk/deps/reference_builds/(.*)', svn_url)
  if match:
    repo = '%s.git' % match.group(1)
    return (path, GIT_HOST + 'chromium/reference_builds/%s' % repo)

  # Nothing yet? Oops.
  print 'No match for %s' % svn_url
