#!/usr/bin/env node
// Tour graph analysis script

const fs = require('fs');

const inputPath = process.argv[2];
const outputPath = process.argv[3];

if (!inputPath || !outputPath) {
  console.error('Usage: node ua-tour-analyze.js <input.json> <output.json>');
  process.exit(1);
}

let data;
try {
  data = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
} catch (e) {
  console.error('Failed to read/parse input:', e.message);
  process.exit(1);
}

const { nodes, edges, layers } = data;

// Build lookup maps
const nodeMap = {};
for (const n of nodes) {
  nodeMap[n.id] = n;
}

// A. Fan-In (how many nodes point TO this node)
const fanIn = {};
const fanOut = {};
for (const n of nodes) {
  fanIn[n.id] = 0;
  fanOut[n.id] = 0;
}
for (const e of edges) {
  if (fanIn[e.target] !== undefined) fanIn[e.target]++;
  if (fanOut[e.source] !== undefined) fanOut[e.source]++;
}

const fanInRanking = Object.entries(fanIn)
  .map(([id, count]) => ({ id, fanIn: count, name: nodeMap[id]?.name || id }))
  .sort((a, b) => b.fanIn - a.fanIn)
  .slice(0, 20);

const fanOutRanking = Object.entries(fanOut)
  .map(([id, count]) => ({ id, fanOut: count, name: nodeMap[id]?.name || id }))
  .sort((a, b) => b.fanOut - a.fanOut)
  .slice(0, 20);

// C. Entry Point Candidates
const totalNodes = nodes.length;
const fanOutValues = Object.values(fanOut).sort((a, b) => a - b);
const top10PctThreshold = fanOutValues[Math.floor(totalNodes * 0.9)] || 0;
const bottom25PctThreshold = fanOutValues[Math.floor(totalNodes * 0.25)] || 0;

const scores = {};
for (const n of nodes) {
  let score = 0;
  const filePath = n.filePath || '';
  const name = n.name || '';

  // Documentation bonus
  if (n.type === 'document' || n.type === 'file') {
    // README-like docs get high score
    if (name.toLowerCase() === 'readme.md') score += 5;
    else if (filePath.split('/').length <= 2 && name.endsWith('.md')) score += 2;
  }

  // Code entry point names
  const entryNames = [
    'index.ts','index.js','main.ts','main.js','app.ts','app.js',
    'server.ts','server.js','mod.rs','main.go','main.py','main.rs',
    'manage.py','app.py','wsgi.py','asgi.py','run.py','__main__.py',
    'Application.java','Main.java','Program.cs','config.ru','index.php',
    'App.swift','Application.kt','main.cpp','main.c'
  ];
  if (entryNames.includes(name)) score += 3;

  // Depth: root or one level deep
  const depth = filePath.split('/').length;
  if (depth <= 2) score += 1;

  // High fan-out
  if (fanOut[n.id] >= top10PctThreshold) score += 1;

  // Low fan-in
  if (fanIn[n.id] <= bottom25PctThreshold) score += 1;

  scores[n.id] = score;
}

const entryPointCandidates = Object.entries(scores)
  .map(([id, score]) => ({
    id,
    score,
    name: nodeMap[id]?.name || id,
    summary: nodeMap[id]?.summary || ''
  }))
  .sort((a, b) => b.score - a.score)
  .slice(0, 5);

// D. BFS traversal - find top CODE entry point (skip pure docs for BFS)
const codeEntryPoint = entryPointCandidates.find(c => {
  const n = nodeMap[c.id];
  return n && n.type !== 'document';
}) || entryPointCandidates[0];

const bfsStart = codeEntryPoint ? codeEntryPoint.id : (nodes[0] ? nodes[0].id : null);

// Build adjacency (imports/calls edges only — fall back to all edges if none)
const adjImports = {};
for (const n of nodes) adjImports[n.id] = [];
const importEdgeTypes = ['imports', 'calls'];
const relevantEdges = edges.filter(e => importEdgeTypes.includes(e.type));
const edgesToUse = relevantEdges.length > 0 ? relevantEdges : edges;
for (const e of edgesToUse) {
  if (adjImports[e.source]) adjImports[e.source].push(e.target);
}

const bfsOrder = [];
const depthMap = {};
const byDepth = {};
if (bfsStart) {
  const visited = new Set();
  const queue = [[bfsStart, 0]];
  visited.add(bfsStart);
  while (queue.length > 0) {
    const [node, depth] = queue.shift();
    bfsOrder.push(node);
    depthMap[node] = depth;
    if (!byDepth[depth]) byDepth[depth] = [];
    byDepth[depth].push(node);
    for (const neighbor of (adjImports[node] || [])) {
      if (!visited.has(neighbor)) {
        visited.add(neighbor);
        queue.push([neighbor, depth + 1]);
      }
    }
  }
}

// E. Non-code files
const nonCodeFiles = {
  documentation: [],
  infrastructure: [],
  data: [],
  config: []
};
for (const n of nodes) {
  if (n.type === 'document') {
    nonCodeFiles.documentation.push({ id: n.id, name: n.name, summary: n.summary });
  } else if (['service','pipeline','resource'].includes(n.type)) {
    nonCodeFiles.infrastructure.push({ id: n.id, name: n.name, type: n.type, summary: n.summary });
  } else if (['table','schema','endpoint'].includes(n.type)) {
    nonCodeFiles.data.push({ id: n.id, name: n.name, type: n.type, summary: n.summary });
  } else if (n.type === 'config') {
    nonCodeFiles.config.push({ id: n.id, name: n.name, summary: n.summary });
  }
}

// F. Tightly coupled clusters
const edgeSet = new Set(edges.map(e => `${e.source}-->${e.target}`));
const bidirectional = [];
const nodeIds = nodes.map(n => n.id);
for (let i = 0; i < nodeIds.length; i++) {
  for (let j = i + 1; j < nodeIds.length; j++) {
    const a = nodeIds[i], b = nodeIds[j];
    if (edgeSet.has(`${a}-->${b}`) && edgeSet.has(`${b}-->${a}`)) {
      bidirectional.push([a, b]);
    }
  }
}

// Expand clusters
const clusters = [];
const inCluster = new Set();
for (const [a, b] of bidirectional) {
  if (inCluster.has(a) && inCluster.has(b)) continue;
  const cluster = new Set([a, b]);
  // Try expanding
  for (const n of nodeIds) {
    if (cluster.has(n)) continue;
    let connections = 0;
    for (const m of cluster) {
      if (edgeSet.has(`${n}-->${m}`) || edgeSet.has(`${m}-->${n}`)) connections++;
    }
    if (connections >= 2) cluster.add(n);
  }
  // Count edges within cluster
  let edgeCount = 0;
  const members = [...cluster];
  for (let i = 0; i < members.length; i++) {
    for (let j = 0; j < members.length; j++) {
      if (i !== j && edgeSet.has(`${members[i]}-->${members[j]}`)) edgeCount++;
    }
  }
  clusters.push({ nodes: members, edgeCount });
  for (const m of members) inCluster.add(m);
}
clusters.sort((a, b) => b.edgeCount - a.edgeCount);

// G. Layers
const layerInfo = {
  count: (layers || []).length,
  list: (layers || []).map(l => ({ id: l.id, name: l.name, description: l.description }))
};

// H. Node Summary Index
const nodeSummaryIndex = {};
for (const n of nodes) {
  nodeSummaryIndex[n.id] = { name: n.name, type: n.type, summary: n.summary || '' };
}

const output = {
  scriptCompleted: true,
  entryPointCandidates,
  fanInRanking,
  fanOutRanking,
  bfsTraversal: {
    startNode: bfsStart,
    order: bfsOrder,
    depthMap,
    byDepth
  },
  nonCodeFiles,
  clusters: clusters.slice(0, 10),
  layers: layerInfo,
  nodeSummaryIndex,
  totalNodes: nodes.length,
  totalEdges: edges.length
};

try {
  fs.writeFileSync(outputPath, JSON.stringify(output, null, 2));
} catch (e) {
  console.error('Failed to write output:', e.message);
  process.exit(1);
}

console.log(`Analysis complete: ${nodes.length} nodes, ${edges.length} edges`);
process.exit(0);
