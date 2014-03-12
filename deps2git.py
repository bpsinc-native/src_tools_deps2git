#!/usr/bin/python
# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Convert SVN based DEPS into .DEPS.git for use with NewGit."""

import collections
import json
import optparse
import os
import Queue
import shutil
import subprocess
import sys
import time

from multiprocessing.pool import ThreadPool

import deps_utils
import git_tools
import svn_to_git_public


# This is copied from depot_tools/gclient.py
DEPS_OS_CHOICES = {
    "win32": "win",
    "win": "win",
    "cygwin": "win",
    "darwin": "mac",
    "mac": "mac",
    "unix": "unix",
    "linux": "unix",
    "linux2": "unix",
    "linux3": "unix",
    "android": "android",
}

def SplitScmUrl(url):
  """Given a repository, return a set containing the URL and the revision."""
  url_split = url.split('@')
  scm_url = url_split[0]
  scm_rev = 'HEAD'
  if len(url_split) == 2:
    scm_rev = url_split[1]
  return (scm_url, scm_rev)


def SvnRevToGitHash(svn_rev, git_url, repos_path, workspace, dep_path,
                    git_host, svn_branch_name=None, cache_dir=None):
  """Convert a SVN revision to a Git commit id."""
  git_repo = None
  if git_url.startswith(git_host):
    git_repo = git_url.replace(git_host, '')
  else:
    raise Exception('Unknown git server %s, host %s' % (git_url, git_host))
  if repos_path is None and workspace is None and cache_dir is None:
    # We're running without a repository directory (i.e. no -r option).
    # We cannot actually find the commit id, but this mode is useful
    # just for testing the URL mappings.  Produce an output file that
    # can't actually be used, but can be eyeballed for correct URLs.
    return 'xxx-r%s' % svn_rev
  if repos_path:
    mirror = True
    git_repo_path = os.path.join(repos_path, git_repo)
    if not os.path.exists(git_repo_path) or not os.listdir(git_repo_path):
      git_tools.Clone(git_url, git_repo_path, mirror)
  elif cache_dir:
    mirror = 'bare'
    git_tools.Clone(git_url, None, mirror, cache_dir=cache_dir)
    git_repo_path = git_tools.GetCacheRepoDir(git_url, cache_dir)
  else:
    mirror = False
    git_repo_path = os.path.join(workspace, dep_path)
    if (os.path.exists(git_repo_path) and
        not os.path.exists(os.path.join(git_repo_path, '.git'))):
      # shutil.rmtree is unreliable on windows
      if sys.platform == 'win32':
        for _ in xrange(3):
          if not subprocess.call(['cmd.exe', '/c', 'rd', '/q', '/s',
                                  os.path.normcase(git_repo_path)]):
            break
          time.sleep(3)
      else:
        shutil.rmtree(git_repo_path)
    if not os.path.exists(git_repo_path):
      git_tools.Clone(git_url, git_repo_path, mirror)

  if svn_branch_name:
    # svn branches are mirrored with:
    # branches = branches/*:refs/remotes/branch-heads/*
    if mirror:
      refspec = 'refs/branch-heads/' + svn_branch_name
    else:
      refspec = 'refs/remotes/branch-heads/' + svn_branch_name
  else:
    if mirror:
      refspec = 'refs/heads/master'
    else:
      refspec = 'refs/remotes/origin/master'

  try:
    return git_tools.Search(git_repo_path, svn_rev, mirror, refspec, git_url)
  except Exception:
    print >> sys.stderr, '%s <-> ERROR' % git_repo_path
    raise

def ConvertDepsToGit(deps, options, deps_vars, svn_deps_vars, svn_to_git_objs,
                     deps_overrides):
  """Convert a 'deps' section in a DEPS file from SVN to Git."""
  new_deps = {}
  bad_git_urls = set([])

  # Populate our deps list.
  deps_to_process = {}
  for dep, dep_url in deps.iteritems():
    if not dep_url:  # dep is 'None' and emitted to exclude the dep
      new_deps[dep] = None
      continue

    # Get the URL and the revision/hash for this dependency.
    dep_url, dep_rev = SplitScmUrl(deps[dep])

    path = dep
    git_url = dep_url
    svn_branch = None
    git_host = dep_url

    if not dep_url.endswith('.git'):
      # Convert this SVN URL to a Git URL.
      for svn_git_converter in svn_to_git_objs:
        converted_data = svn_git_converter.SvnUrlToGitUrl(dep, dep_url)
        if converted_data:
          path, git_url, git_host = converted_data[:3]
          if len(converted_data) > 3:
            svn_branch = converted_data[3]
          break
      else:
        # Make all match failures fatal to catch errors early. When a match is
        # found, we break out of the loop so the exception is not thrown.
        raise Exception('No match found for %s' % dep_url)

    Job = collections.namedtuple('Job', ['git_url', 'dep_url', 'path',
                                         'git_host', 'dep_rev', 'svn_branch'])
    deps_to_process[dep] = Job(
        git_url, dep_url, path, git_host, dep_rev, svn_branch)

  # Lets pre-cache all of the git repos now if we have cache_dir turned on.
  if options.cache_dir:
    if not os.path.isdir(options.cache_dir):
      os.makedirs(options.cache_dir)
    pool = ThreadPool(processes=len(deps_to_process))
    output_queue = Queue.Queue()
    num_threads = 0
    for git_url, _, _, _, _, _ in deps_to_process.itervalues():
      print 'Populating cache for %s' % git_url
      num_threads += 1
      pool.apply_async(git_tools.Clone, (git_url, None, 'bare',
                                         output_queue, options.cache_dir,
                                         options.shallow))
    pool.close()

    # Stream stdout line by line.
    sec_since = 0
    while num_threads > 0:
      try:
        line = output_queue.get(block=True, timeout=1)
        sec_since = 0
      except Queue.Empty:
        sec_since += 1
        line = ('Main> Heartbeat ping. We are still alive!! '
                'Seconds since last output: %d sec' % sec_since)
      if line is None:
        num_threads -= 1
      else:
        print line
    pool.join()


  for dep, items in deps_to_process.iteritems():
    git_url, dep_url, path, git_host, dep_rev, svn_branch = items
    if options.verify:
      delay = 0.5
      success = False
      for try_index in range(1, 6):
        print >> sys.stderr, 'checking %s (try #%d) ...' % (git_url, try_index),
        if git_tools.Ping(git_url, verbose=True):
          print >> sys.stderr, ' success'
          success = True
          break

        print >> sys.stderr, ' failure'
        print >> sys.stderr, 'sleeping for %.01f seconds ...' % delay
        time.sleep(delay)
        delay *= 2

      if not success:
        bad_git_urls.update([git_url])

    # Get the Git hash based off the SVN rev.
    git_hash = ''
    if dep_rev != 'HEAD':
      if dep in deps_overrides:
        # Transfer any required variables over from SVN DEPS.
        if not deps_overrides[dep] in svn_deps_vars:
          raise Exception('Missing DEPS variable: %s' % deps_overrides[dep])
        deps_vars[deps_overrides[dep]] = (
            '@' + svn_deps_vars[deps_overrides[dep]].lstrip('@'))
        # Tag this variable as needing a transform by Varify() later.
        git_hash = '%s_%s' % (deps_utils.VARIFY_MARKER_TAG_PREFIX,
                              deps_overrides[dep])
      else:
        # Pass-through the hash for Git repositories. Resolve the hash for
        # subversion repositories.
        if dep_url.endswith('.git'):
          git_hash = '@%s' % dep_rev
        else:
          git_hash = '@%s' % SvnRevToGitHash(
              dep_rev, git_url, options.repos, options.workspace, path,
              git_host, svn_branch, options.cache_dir)

    # If this is webkit, we need to add the var for the hash.
    if dep == 'src/third_party/WebKit' and dep_rev:
      deps_vars['webkit_rev'] = git_hash
      git_hash = 'VAR_WEBKIT_REV'

    # Hack to preserve the angle_revision variable in .DEPS.git.
    # This will go away as soon as deps2git does.
    if dep == 'src/third_party/angle' and git_hash:
      # Cut the leading '@' so this variable has the same semantics in
      # DEPS and .DEPS.git.
      deps_vars['angle_revision'] = git_hash[1:]
      git_hash = 'VAR_ANGLE_REVISION'

    # Add this Git dep to the new deps.
    new_deps[path] = '%s%s' % (git_url, git_hash)

  return new_deps, bad_git_urls


def main():
  parser = optparse.OptionParser()
  parser.add_option('-d', '--deps', default='DEPS',
                    help='path to the DEPS file to convert')
  parser.add_option('-o', '--out',
                    help='path to the converted DEPS file (default: stdout)')
  parser.add_option('-t', '--type',
                    help='[DEPRECATED] type of DEPS file (public, etc)')
  parser.add_option('-x', '--extra-rules',
                    help='Path to file with additional conversion rules.')
  parser.add_option('-r', '--repos',
                    help='path to the directory holding all the Git repos')
  parser.add_option('-w', '--workspace', metavar='PATH',
                    help='top level of a git-based gclient checkout')
  parser.add_option('-c', '--cache_dir',
                    help='top level of a gclient git cache diretory.')
  parser.add_option('-s', '--shallow', action='store_true',
                    help='Use shallow checkouts when populating cache dirs.')
  parser.add_option('--verify', action='store_true',
                    help='ping each Git repo to make sure it exists')
  parser.add_option('--json',
                    help='path to a JSON file for machine-readable output')
  options = parser.parse_args()[0]

  # Get the content of the DEPS file.
  deps_content = deps_utils.GetDepsContent(options.deps)
  (deps, deps_os, include_rules, skip_child_includes, hooks,
   svn_deps_vars) = deps_content

  if options.extra_rules and options.type:
    parser.error('Can\'t specify type and extra-rules at the same time.')
  elif options.type:
    options.extra_rules = os.path.join(
        os.path.abspath(os.path.dirname(__file__)),
        'svn_to_git_%s.py' % options.type)
  if options.cache_dir and options.repos:
    parser.error('Can\'t specify both cache_dir and repos at the same time.')
  if options.shallow and not options.cache_dir:
    parser.error('--shallow only supported with --cache_dir.')

  if options.cache_dir:
    options.cache_dir = os.path.abspath(options.cache_dir)

  if options.extra_rules and not os.path.exists(options.extra_rules):
    raise Exception('Can\'t locate rules file "%s".' % options.extra_rules)

  # Create a var containing the Git and Webkit URL, this will make it easy for
  # people to use a mirror instead.
  git_url = 'https://chromium.googlesource.com'
  deps_vars = {
      'git_url': git_url,
      'webkit_url': git_url + '/chromium/blink.git',
  }

  # Find and load svn_to_git_* modules that handle the URL mapping.
  svn_to_git_objs = [svn_to_git_public]
  deps_overrides = getattr(svn_to_git_public, 'DEPS_OVERRIDES', {}).copy()
  if options.extra_rules:
    rules_dir, rules_file = os.path.split(options.extra_rules)
    rules_file_base = os.path.splitext(rules_file)[0]
    sys.path.insert(0, rules_dir)
    svn_to_git_mod = __import__(rules_file_base)
    svn_to_git_objs.insert(0, svn_to_git_mod)
    # Allow extra_rules file to override rules in svn_to_git_public.
    deps_overrides.update(getattr(svn_to_git_mod, 'DEPS_OVERRIDES', {}))

  # If a workspace parameter is given, and a .gclient file is present, limit
  # DEPS conversion to only the repositories that are actually used in this
  # checkout.  Also, if a cache dir is specified in .gclient, honor it.
  if options.workspace and os.path.exists(
      os.path.join(options.workspace, '.gclient')):
    gclient_file = os.path.join(options.workspace, '.gclient')
    gclient_dict = {}
    try:
      execfile(gclient_file, {}, gclient_dict)
    except IOError:
      print >> sys.stderr, 'Could not open %s' % gclient_file
      raise
    except SyntaxError:
      print >> sys.stderr, 'Could not parse %s' % gclient_file
      raise
    target_os = gclient_dict.get('target_os', [])
    if not target_os or not gclient_dict.get('target_os_only'):
      target_os.append(DEPS_OS_CHOICES.get(sys.platform, 'unix'))
    if 'all' not in target_os:
      deps_os = dict([(k, v) for k, v in deps_os.iteritems() if k in target_os])
    if not options.cache_dir and 'cache_dir' in gclient_dict:
      options.cache_dir = os.path.abspath(gclient_dict['cache_dir'])

  # Convert the DEPS file to Git.
  deps, baddeps = ConvertDepsToGit(
      deps, options, deps_vars, svn_deps_vars, svn_to_git_objs, deps_overrides)
  for os_dep in deps_os:
    deps_os[os_dep], os_bad_deps = ConvertDepsToGit(
        deps_os[os_dep], options, deps_vars, svn_deps_vars,
        svn_to_git_objs, deps_overrides)
    baddeps = baddeps.union(os_bad_deps)

  if options.json:
    with open(options.json, 'w') as f:
      json.dump(list(baddeps), f, sort_keys=True, indent=2)

  if baddeps:
    print >> sys.stderr, ('\nUnable to resolve the following repositories. '
        'Please make sure\nthat any svn URLs have a git mirror associated with '
        'them.\nTo see the exact error, run `git ls-remote [repository]` where'
        '\n[repository] is the URL ending in .git (strip off the @revision\n'
        'number.) For more information, visit http://code.google.com\n'
        '/p/chromium/wiki/UsingGit#Adding_new_repositories_to_DEPS.\n')
    for dep in baddeps:
      print >> sys.stderr, ' ' + dep
    return 2
  else:
    if options.verify:
      print >> sys.stderr, ('\nAll referenced repositories were successfully '
                            'resolved.')
      return 0

  # Write the DEPS file to disk.
  deps_utils.WriteDeps(options.out, deps_vars, deps, deps_os, include_rules,
                       skip_child_includes, hooks)
  return 0


if '__main__' == __name__:
  sys.exit(main())
