#!/usr/bin/python
# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Convert SVN based DEPS into .DEPS.git for use with NewGit."""

import collections
import json
import optparse
import os
import sys
import time

from multiprocessing.pool import ThreadPool

import deps_utils
import git_tools
import svn_to_git_public


def SplitScmUrl(url):
  """Given a repository, return a set containing the URL and the revision."""
  url_split = url.split('@')
  scm_url = url_split[0]
  scm_rev = 'HEAD'
  if len(url_split) == 2:
    scm_rev = url_split[1]
  return (scm_url, scm_rev)


def _NormalizeGitURL(url):
  '''Takes a git url, strips the scheme, and ensures it ends with '.git'.'''
  separator = '://'
  idx = url.find(separator)
  if idx != -1:
    url = url[idx+len(separator):]
  if not url.endswith('.git'):
    url += '.git'
  return url


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
  mirror = False
  if repos_path:
    git_repo_path = os.path.join(repos_path, git_repo)
    mirror = True
  elif cache_dir:
    git_repo_path = os.path.join(
        cache_dir,
        _NormalizeGitURL(git_url).replace('-', '--').replace('/', '-'))
    mirror = 'bare'
  else:
    git_repo_path = os.path.join(workspace, dep_path)
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
  except git_tools.AbnormalExit:
    # The bare repository clone probably got interrupted. Lets blow away the
    # bare repo and reclone.
    if mirror == 'bare':
      deps_utils.RemoveDirectory(git_repo_path)
      git_tools.Clone(git_url, git_repo_path, mirror)
      return git_tools.Search(git_repo_path, svn_rev, mirror, refspec, git_url)
    raise

def ConvertDepsToGit(deps, options, deps_vars, svn_deps_vars):
  """Convert a 'deps' section in a DEPS file from SVN to Git."""
  new_deps = {}
  bad_git_urls = set([])

  svn_to_git_objs = [svn_to_git_public]
  if options.extra_rules:
    rules_dir, rules_file = os.path.split(options.extra_rules)
    rules_file_base = os.path.splitext(rules_file)[0]
    sys.path.insert(0, rules_dir)
    svn_to_git_objs.insert(0, __import__(rules_file_base))

  deps_overrides = {}
  # Allow extra_rules file to override rules in public file.
  for svn_to_git_obj in reversed(svn_to_git_objs):
    deps_overrides.update(getattr(svn_to_git_obj, 'DEPS_OVERRIDES', {}))

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
    pool = ThreadPool()
    for git_url, _, _, _, _, _ in deps_to_process.itervalues():
      git_repo_path = os.path.join(
          options.cache_dir,
          _NormalizeGitURL(git_url).replace('-', '--').replace('/', '-'))
      print 'Caching %s' % git_url
      if not os.path.exists(git_repo_path):
        pool.apply_async(git_tools.Clone, (git_url, git_repo_path, 'bare'))
    pool.close()
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

  # Convert the DEPS file to Git.
  deps, baddeps = ConvertDepsToGit(deps, options, deps_vars, svn_deps_vars)
  for os_dep in deps_os:
    deps_os[os_dep], os_bad_deps = ConvertDepsToGit(
        deps_os[os_dep], options, deps_vars, svn_deps_vars)
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
