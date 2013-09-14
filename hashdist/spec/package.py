import os
from os.path import join as pjoin

from .marked_yaml import marked_yaml_load

class PackageSpec(object):
    def __init__(self, doc, build_deps, run_deps):
        self.doc = doc
        self.build_deps = build_deps
        self.run_deps = run_deps        

    @staticmethod
    def load(doc, resolver):
        deps = doc.get('dependencies', {})
        build_deps = PackageSpecSet(resolver, deps.get('build', []))
        run_deps = PackageSpecSet(resolver, deps.get('run', []))
        return PackageSpec(doc, build_deps, run_deps)

class PackageSpecSet(object):
    """
    A dict-like representing a subset of packages, but they are lazily
    loaded
    """
    def __init__(self, resolver, packages):
        self.resolver = resolver
        self.packages = packages
        self._values = None

    def __getitem__(self, key):
        if key not in self.packages:
            raise KeyError('Package %s not found' % key)
        return self.resolver.parse_package(key)

    def values(self):
        if self._values is None:
            self._values = [self[key] for key in self.packages]
        return self._values

    def keys(self):
        return list(self.packages)

    def __repr__(self):
        return '<%s: %r>' % (self.__class__.__name__, self.packages)


_package_spec_cache = {}
class PackageSpecResolver(object):
    def __init__(self, path):
        self.path = path

    def parse_package(self, pkgname):
        filename = os.path.realpath(pjoin(self.path, pkgname, '%s.yaml' % pkgname))
        obj = _package_spec_cache.get(filename, None)
        if obj is None:
            with open(filename) as f:
                doc = marked_yaml_load(f)
            obj = _package_spec_cache[filename] = PackageSpec.load(doc, self)
        return obj

def normalize_stages(stages):
    def normalize_stage(stage):
        # turn before/after into lists
        stage = dict(stage)
        for key in ['before', 'after']:
            if key not in stage:
                stage[key] = []
            elif isinstance(stage[key], basestring):
                stage[key] = [stage[key]]
        return stage
    return [normalize_stage(stage) for stage in stages]


def topological_stage_sort(stages):
    """
    Turns a list of stages with keys name/before/after and turns it
    into an ordered list of stages. Every stage must have a unique
    name. The topological sort visits multiple dependent stages
    alphabetically.
    """
    # note that each stage is shallow-copied for modification below
    stage_by_name = dict((stage['name'], dict(stage)) for stage in stages)
    if len(stage_by_name) != len(stages):
        raise ValueError('`stages` has entries with the same name')
    # convert 'before' to 'after'
    for stage in stages:
        for later_stage_name in stage['before']:
            try:
                later_stage = stage_by_name[later_stage_name]
            except:
                raise ValueError('stage "%s" referred to, but not available' % later_stage_name)
            later_stage['after'] = later_stage['after'] + [stage['name']]  # copy

    visited = set()
    visiting = set()
    ordered_stages = []
    def toposort(stage_name):
        if stage_name in visiting:
            raise ValueError('stage %s participates in stage ordering cycle' % stage_name)
        if stage_name not in visited:
            stage = stage_by_name[stage_name]
            visiting.add(stage_name)
            for earlier_stage_name in stage['after']:
                toposort(earlier_stage_name)
            visiting.remove(stage_name)
            visited.add(stage_name)
            ordered_stages.append(stage)
    for stage_name in sorted(stage_by_name.keys()):
        toposort(stage_name)
    for stage in ordered_stages:
        del stage['after']
        del stage['before']
    return ordered_stages

