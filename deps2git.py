#!/usr/bin/python
# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import optparse
import sys


import deps_utils


def SplitSvnUrl(url):
  """Given a SVN URL, return a set containing the URL and the revision."""
  url_split = url.split('@')
  svn_url = url_split[0]
  svn_rev = 'HEAD'
  if len(url_split) == 2:
    svn_rev = url_split[1]
  return (svn_url, svn_rev)


def SvnRevToGitHash(svn_rev, git_url, repos_path, git_host):
  """Convert a SVN revision to a Git commit id."""
  git_repo = None
  if git_url.startswith(git_host):
    git_repo = git_url.replace(git_host, '')
  else:
    raise Exception('Unknown git server')
  if repos_path is None:
    # We're running without a repository directory (i.e. no -r option).
    # We cannot actually find the commit id, but this mode is useful
    # just for testing the URL mappings.  Produce an output file that
    # can't actually be used, but can be eyeballed for correct URLs.
    return ('xxx-r%s' % svn_rev)
  # TODO(unknown_coder): Most of the errors happen when people add new repos
  # that actually matches one of our expressions but dont exist yet on
  # git.chromium.org.  We should probably at least ping git_url to make sure it
  # exists.
  git_repo_path = os.path.join(repos_path, git_repo)
  if not os.path.exists(git_repo_path):
    git_tools.Clone(git_url, git_repo_path)
  git_tools.Fetch(git_repo_path)
  return git_tools.Search(git_repo_path, svn_rev)


def ConvertDepsToGit(deps, repos, deps_type, vars)
  """Convert a 'deps' section in a DEPS file from SVN to Git."""
  new_deps = {}
  deps_module = os.path.join(os.path.dirname(__file__),
                             'svn_to_git_%s' % deps_type)
  if not os.path.exists(depos_module):
    raise Exception('invalid DEPS type')
  svn_to_git = __import__(deps_module)

  for dep in deps:
    # Get the SVN URL and the SVN rev for this dep.
    (svn_url, svn_rev) = SplitSvnUrl(deps[dep])

    # Convert this SVN URL to a Git URL.
    (path, git_url) = svn_to_git.SvnUrlToGitUrl(dep, svn_url)

    if not path or not git_url:
      # We skip this path, this must not be required with Git.
      continue

    # Get the Git hash based off the SVN rev.
    git_hash = ''
    if svn_rev != 'HEAD':
      git_hash = '@%s' % SvnRevToGitHash(svn_rev, git_url, repos,
          svn_to_git.GIT_HOST)

    # If this is webkit, we need to add the var for the hash.
    if dep == 'src/third_party/WebKit/Source':
      vars['webkit_rev'] = git_hash
      git_hash = 'VAR_WEBKIT_REV'

    # Add this Git dep to the new deps.
    new_deps[path] = '%s%s' % (git_url, git_hash)

  return new_deps


def main():
  parser = optparse.OptionParser()
  parser.add_option('-d', '--deps',
                    help='path to the DEPS file to convert')
  parser.add_option('-o', '--out',
                    help='path to the converted DEPS file')
  parser.add_option('-t', '--type', default='public',
                    help='type of DEPS file (public, etc)')
  parser.add_option('-r', '--repos',
                    help='path to the directory holding all the Git repos')
  options, args = parser.parse_args()

  # Get the content of the DEPS file.
  deps_content =  deps_utils.GetDepsContent(options.deps)
  (deps, deps_os, include_rules, skip_child_includes, hooks) = deps_content

  # Create a var containing the Git and Webkit URL, this will make it easy for
  # people to use a mirror instead.
  vars = {'git_url': 'http://git.chromium.org',
          'webkit_url': 'http://git.chromium.org/external/WebKit_trimmed.git'}

  # Convert the DEPS file to Git.
  deps = ConvertDepsToGit(deps, options.repos, options.type, vars)
  for os_dep in deps_os:
    deps_os[os_dep] = ConvertDepsToGit(deps_os[os_dep], options.repos,
                                       options.type, vars)

  # Write the DEPS file to disk.
  deps_utils.WriteDeps(options.out, vars, deps, deps_os, include_rules,
                       skip_child_includes, hooks)
  return 0

if '__main__' == __name__:
  sys.exit(main())
