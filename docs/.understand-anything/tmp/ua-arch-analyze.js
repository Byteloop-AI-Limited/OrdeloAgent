#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const inputPath = process.argv[2];
const outputPath = process.argv[3];

if (!inputPath || !outputPath) {
  console.error('Usage: node ua-arch-analyze.js <input.json> <output.json>');
  process.exit(1);
}

let input;
try {
  input = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
} catch (e) {
  console.error('Failed to read/parse input:', e.message);
  process.exit(1);
}

const { fileNodes, importEdges, allEdges } = input;

// ---- A. Directory Grouping ----
// Compute common prefix
function commonPrefix(paths) {
  if (!paths.length) return '';
  const parts = paths[0].split('/');
  let prefix = [];
  for (let i = 0; i < parts.length - 1; i++) {
    if (paths.every(p => p.split('/')[i] === parts[i])) {
      prefix.push(parts[i]);
    } else {
      break;
    }
  }
  return prefix.join('/');
}

const filePaths = fileNodes.map(n => n.filePath);
const cp = commonPrefix(filePaths);

function getGroupKey(filePath, commonPfx) {
  const stripped = commonPfx ? filePath.slice(commonPfx.length).replace(/^\//, '') : filePath;
  const segments = stripped.split('/');
  if (segments.length <= 1) {
    // flat — group by extension pattern
    const name = segments[0];
    if (/\.(test|spec)\.[^.]+$/.test(name)) return 'test';
    if (/\.(config|cfg)\.[^.]+$/.test(name) || name.endsWith('.config.js') || name.endsWith('.config.ts')) return 'config';
    if (name.endsWith('.html')) return 'html';
    if (name.endsWith('.md') || name.endsWith('.rst')) return 'docs-root';
    const ext = name.split('.').pop();
    return ext || 'root';
  }
  return segments[0];
}

const directoryGroups = {};
for (const node of fileNodes) {
  const group = getGroupKey(node.filePath, cp);
  if (!directoryGroups[group]) directoryGroups[group] = [];
  directoryGroups[group].push(node.id);
}

// ---- B. Node Type Grouping ----
const nodeTypeGroups = {};
for (const node of fileNodes) {
  const t = node.type || 'file';
  if (!nodeTypeGroups[t]) nodeTypeGroups[t] = [];
  nodeTypeGroups[t].push(node.id);
}

// ---- C. Import fan-in / fan-out ----
const fileFanOut = {};
const fileFanIn = {};
for (const node of fileNodes) {
  fileFanOut[node.id] = 0;
  fileFanIn[node.id] = 0;
}
for (const edge of importEdges) {
  if (fileFanOut[edge.source] !== undefined) fileFanOut[edge.source]++;
  if (fileFanIn[edge.target] !== undefined) fileFanIn[edge.target]++;
}

// ---- D. Cross-category dependency analysis ----
const nodeTypeMap = {};
for (const node of fileNodes) nodeTypeMap[node.id] = node.type || 'file';

const crossCategoryMap = {};
for (const edge of allEdges) {
  const fromType = nodeTypeMap[edge.source] || 'unknown';
  const toType = nodeTypeMap[edge.target] || 'unknown';
  const key = `${fromType}|${toType}|${edge.type}`;
  crossCategoryMap[key] = (crossCategoryMap[key] || 0) + 1;
}
const crossCategoryEdges = Object.entries(crossCategoryMap).map(([key, count]) => {
  const [fromType, toType, edgeType] = key.split('|');
  return { fromType, toType, edgeType, count };
});

// ---- E. Inter-group import frequency ----
const nodeGroupMap = {};
for (const [group, ids] of Object.entries(directoryGroups)) {
  for (const id of ids) nodeGroupMap[id] = group;
}

const interGroupMap = {};
for (const edge of importEdges) {
  const fromGroup = nodeGroupMap[edge.source];
  const toGroup = nodeGroupMap[edge.target];
  if (fromGroup && toGroup && fromGroup !== toGroup) {
    const key = `${fromGroup}|${toGroup}`;
    interGroupMap[key] = (interGroupMap[key] || 0) + 1;
  }
}
const interGroupImports = Object.entries(interGroupMap).map(([key, count]) => {
  const [from, to] = key.split('|');
  return { from, to, count };
}).sort((a, b) => b.count - a.count);

// ---- F. Intra-group import density ----
const intraGroupDensity = {};
for (const group of Object.keys(directoryGroups)) {
  const members = new Set(directoryGroups[group]);
  let internal = 0;
  let total = 0;
  for (const edge of importEdges) {
    const srcInGroup = members.has(edge.source);
    const tgtInGroup = members.has(edge.target);
    if (srcInGroup || tgtInGroup) {
      total++;
      if (srcInGroup && tgtInGroup) internal++;
    }
  }
  intraGroupDensity[group] = {
    internalEdges: internal,
    totalEdges: total,
    density: total > 0 ? internal / total : 0
  };
}

// ---- G. Directory pattern matching ----
const PATTERNS = {
  routes: 'api', api: 'api', controllers: 'api', endpoints: 'api', handlers: 'api',
  services: 'service', core: 'service', lib: 'service', domain: 'service', logic: 'service',
  models: 'data', db: 'data', data: 'data', persistence: 'data', repository: 'data', entities: 'data',
  components: 'ui', views: 'ui', pages: 'ui', ui: 'ui', layouts: 'ui', screens: 'ui',
  middleware: 'middleware', plugins: 'middleware', interceptors: 'middleware', guards: 'middleware',
  utils: 'utility', helpers: 'utility', common: 'utility', shared: 'utility', tools: 'utility',
  config: 'config', constants: 'config', env: 'config', settings: 'config',
  '__tests__': 'test', test: 'test', tests: 'test', spec: 'test', specs: 'test',
  types: 'types', interfaces: 'types', schemas: 'types', contracts: 'types', dtos: 'types',
  hooks: 'hooks',
  store: 'state', state: 'state', reducers: 'state', actions: 'state', slices: 'state',
  assets: 'assets', static: 'assets', public: 'assets',
  migrations: 'data',
  docs: 'documentation', documentation: 'documentation', wiki: 'documentation',
  deploy: 'infrastructure', deployment: 'infrastructure', infra: 'infrastructure', infrastructure: 'infrastructure',
  k8s: 'infrastructure', kubernetes: 'infrastructure', helm: 'infrastructure',
  terraform: 'infrastructure', docker: 'infrastructure',
  '.github': 'ci-cd', '.gitlab': 'ci-cd', '.circleci': 'ci-cd',
  bin: 'entry', cmd: 'entry',
  'docs-root': 'documentation',
  md: 'documentation',
  html: 'interactive',
};

const patternMatches = {};
for (const group of Object.keys(directoryGroups)) {
  patternMatches[group] = PATTERNS[group.toLowerCase()] || 'unknown';
}

// ---- H. Deployment topology detection ----
const allFilePaths = fileNodes.map(n => n.filePath);
const deploymentTopology = {
  hasDockerfile: allFilePaths.some(p => /Dockerfile/.test(p)),
  hasCompose: allFilePaths.some(p => /docker-compose/.test(p)),
  hasK8s: allFilePaths.some(p => /k8s|kubernetes|\.yaml$/.test(p)),
  hasTerraform: allFilePaths.some(p => /\.tf$|\.tfvars$/.test(p)),
  hasCI: allFilePaths.some(p => /\.github|\.gitlab|Jenkinsfile/.test(p)),
  infraFiles: allFilePaths.filter(p =>
    /Dockerfile|docker-compose|\.tf$|\.tfvars$|\.github\/workflows|\.gitlab-ci|Jenkinsfile|Makefile/.test(p)
  )
};

// ---- I. Data pipeline detection ----
const dataPipeline = {
  schemaFiles: allFilePaths.filter(p => /\.graphql$|\.gql$|\.proto$|schema\.sql$/.test(p)),
  migrationFiles: allFilePaths.filter(p => /migrations?\//.test(p)),
  dataModelFiles: allFilePaths.filter(p => /models?\/|entities\//.test(p)),
  apiHandlerFiles: allFilePaths.filter(p => /routes?\/|controllers?\/|handlers?\//.test(p))
};

// ---- J. Documentation coverage ----
const groups = Object.keys(directoryGroups);
const groupsWithDocs = groups.filter(g => {
  const members = directoryGroups[g];
  return members.some(id => {
    const node = fileNodes.find(n => n.id === id);
    return node && (node.filePath.endsWith('.md') || node.filePath.endsWith('.rst') || node.name === 'README.md');
  });
});
const docCoverage = {
  groupsWithDocs: groupsWithDocs.length,
  totalGroups: groups.length,
  coverageRatio: groups.length > 0 ? groupsWithDocs.length / groups.length : 0,
  undocumentedGroups: groups.filter(g => !groupsWithDocs.includes(g))
};

// ---- K. Dependency direction ----
const dependencyDirection = interGroupImports.map(({ from, to, count }) => ({
  dependent: from,
  dependsOn: to
}));

// ---- File stats ----
const filesPerGroup = {};
for (const [g, ids] of Object.entries(directoryGroups)) {
  filesPerGroup[g] = ids.length;
}
const nodeTypeCounts = {};
for (const [t, ids] of Object.entries(nodeTypeGroups)) {
  nodeTypeCounts[t] = ids.length;
}

const result = {
  scriptCompleted: true,
  directoryGroups,
  nodeTypeGroups,
  crossCategoryEdges,
  interGroupImports,
  intraGroupDensity,
  patternMatches,
  deploymentTopology,
  dataPipeline,
  docCoverage,
  dependencyDirection,
  fileStats: {
    totalFileNodes: fileNodes.length,
    filesPerGroup,
    nodeTypeCounts
  },
  fileFanIn,
  fileFanOut
};

try {
  fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));
} catch (e) {
  console.error('Failed to write output:', e.message);
  process.exit(1);
}

console.log('Analysis complete. Total nodes:', fileNodes.length);
process.exit(0);
