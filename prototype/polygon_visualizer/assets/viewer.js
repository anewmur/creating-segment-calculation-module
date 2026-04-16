(function() {
  const svg = document.getElementById('canvas');
  const cont = document.getElementById('svg-container');
  const info = document.getElementById('zoom-info');
  const coord = document.getElementById('coords');
  const hoverOverlay = document.getElementById('hover-overlay');

  const VB0 = { ...window.__VIZ_DATA__.vb };
  let vb = { ...VB0 };
  const WORLD_MIN_Y = window.__VIZ_DATA__.worldMinY;
  const WORLD_MAX_Y = window.__VIZ_DATA__.worldMaxY;
  const flipOffset = window.__VIZ_DATA__.flipOffset;
  // mergeRadius является частью явного контракта window.__VIZ_DATA__.
  const mergeRadius = window.__VIZ_DATA__.mergeRadius;

  let hoverCircle = null;

  document.getElementById('world')
    .setAttribute('transform', `scale(1,-1) translate(0, -${flipOffset})`);

  function applyVB() {
    svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
    info.textContent = Math.round(VB0.w / vb.w * 100) + '%';
    drawGrid();
    updateLabelScale();
  }

  function updateLabelScale() {
    const zoom = VB0.w / vb.w;
    const labels = document.querySelectorAll('#labels .poly-label');

    labels.forEach(label => {
      const baseFontSize = Number(label.dataset.baseFontSize || 12);
      const fontSize = zoom >= 1 ? baseFontSize / zoom : baseFontSize;
      const baseY = Number(label.dataset.baseY);
      const layerIdx = Number(label.dataset.layer || 0);
      const offset = layerIdx * fontSize * 2;

      label.setAttribute('font-size', String(fontSize));
      label.setAttribute('y', String(baseY - offset));
    });

    const vertices = document.querySelectorAll('.vertex');
    vertices.forEach(vertex => {
      const baseR = Number(vertex.dataset.baseR || 3);
      const radius = zoom >= 1 ? baseR / zoom : baseR;
      vertex.setAttribute('r', String(radius));
    });
  }

  function computeGridStep(viewW, viewH) {
    const targetLines = 12;
    const rawStep = Math.max(viewW, viewH) / targetLines;
    const power = Math.floor(Math.log10(rawStep));
    const base = 10 ** power;
    if (rawStep / base > 5) return 10 * base;
    if (rawStep / base > 2) return 5 * base;
    if (rawStep / base > 1) return 2 * base;
    return base;
  }

  function computeGridYLines(viewY, viewH, currentFlipOffset, step) {
    const mathYMin = currentFlipOffset - (viewY + viewH);
    const mathYMax = currentFlipOffset - viewY;
    const yStart = Math.floor(mathYMin / step) * step;
    const yEnd = Math.ceil(mathYMax / step) * step;

    const lines = [];
    const count = Math.round((yEnd - yStart) / step);
    for (let idx = 0; idx <= count; idx += 1) {
      const mathY = yStart + idx * step;
      const svgY = currentFlipOffset - mathY;
      lines.push({ mathY, svgY });
    }
    return lines;
  }

  function drawGrid() {
    const grid = document.getElementById('grid');
    grid.innerHTML = '';

    const labelsGroup = document.getElementById('grid-labels');
    labelsGroup.innerHTML = '';
    const rect = svg.getBoundingClientRect();
    const unitPerPixelX = rect.width > 0 ? vb.w / rect.width : 1;
    const unitPerPixelY = rect.height > 0 ? vb.h / rect.height : 1;
    const edgeOffsetX = 6 * unitPerPixelX;
    const edgeOffsetY = 6 * unitPerPixelY;
    const gridLabelFontSize = 12 * unitPerPixelY;

    const GRID_OVERSCAN_FACTOR = 10;
    const step = computeGridStep(vb.w, vb.h);

    const gridMinX = vb.x - vb.w * GRID_OVERSCAN_FACTOR;
    const gridMaxX = vb.x + vb.w + vb.w * GRID_OVERSCAN_FACTOR;
    const gridMinY = vb.y - vb.h * GRID_OVERSCAN_FACTOR;
    const gridMaxY = vb.y + vb.h + vb.h * GRID_OVERSCAN_FACTOR;

    const mathGridYMin = flipOffset - gridMaxY;
    const mathGridYMax = flipOffset - gridMinY;
    const overscannedYLines = computeGridYLines(gridMinY, gridMaxY - gridMinY, flipOffset, step);

    const xStart = Math.floor(gridMinX / step) * step;
    const xEnd = Math.ceil(gridMaxX / step) * step;

    for (let gridX = xStart; gridX <= xEnd; gridX += step) {
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', gridX);
      line.setAttribute('y1', mathGridYMin);
      line.setAttribute('x2', gridX);
      line.setAttribute('y2', mathGridYMax);
      line.setAttribute('class', 'grid-line');
      grid.appendChild(line);
    }

    for (const { mathY, svgY } of overscannedYLines) {
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', gridMinX);
      line.setAttribute('y1', mathY);
      line.setAttribute('x2', gridMaxX);
      line.setAttribute('y2', mathY);
      line.setAttribute('class', 'grid-line');
      grid.appendChild(line);

      if (svgY >= vb.y && svgY <= vb.y + vb.h) {
        const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        lbl.setAttribute('x', vb.x + edgeOffsetX);
        lbl.setAttribute('y', svgY);
        lbl.setAttribute('font-size', String(gridLabelFontSize));
        lbl.setAttribute('fill', '#000');
        lbl.setAttribute('class', 'grid-label');
        lbl.setAttribute('text-anchor', 'start');
        lbl.setAttribute('dominant-baseline', 'middle');
        lbl.textContent = mathY.toFixed(0);
        labelsGroup.appendChild(lbl);
      }
    }

    const labelXStart = Math.floor(vb.x / step) * step;
    const labelXEnd = Math.ceil((vb.x + vb.w) / step) * step;
    for (let gx = labelXStart; gx <= labelXEnd; gx += step) {
      const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      lbl.setAttribute('x', gx + edgeOffsetX);
      lbl.setAttribute('y', vb.y + edgeOffsetY);
      lbl.setAttribute('font-size', String(gridLabelFontSize));
      lbl.setAttribute('fill', '#000');
      lbl.setAttribute('class', 'grid-label');
      lbl.setAttribute('text-anchor', 'start');
      lbl.setAttribute('dominant-baseline', 'hanging');
      lbl.textContent = gx.toFixed(0);
      labelsGroup.appendChild(lbl);
    }
  }

  function showMergeRadius(worldX, worldY) {
    if (!hoverCircle) {
      hoverCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      hoverCircle.setAttribute('class', 'merge-radius-hover');
      hoverOverlay.appendChild(hoverCircle);
    }

    hoverCircle.setAttribute('cx', String(worldX));
    hoverCircle.setAttribute('cy', String(worldY));
    hoverCircle.setAttribute('r', String(mergeRadius));
  }

  function hideMergeRadius() {
    if (!hoverCircle) {
      return;
    }
    hoverCircle.remove();
    hoverCircle = null;
  }

  cont.addEventListener('wheel', event => {
    event.preventDefault();
    const factor = event.deltaY > 0 ? 1.15 : 1 / 1.15;
    const rect = svg.getBoundingClientRect();
    const mouseX = (event.clientX - rect.left) / rect.width;
    const mouseY = (event.clientY - rect.top) / rect.height;
    const newWidth = vb.w * factor;
    const newHeight = vb.h * factor;
    vb.x += (vb.w - newWidth) * mouseX;
    vb.y += (vb.h - newHeight) * mouseY;
    vb.w = newWidth;
    vb.h = newHeight;
    applyVB();
  }, { passive: false });

  let dragging = false;
  let lastX = 0;
  let lastY = 0;

  cont.addEventListener('mousedown', event => {
    dragging = true;
    lastX = event.clientX;
    lastY = event.clientY;
    cont.classList.add('dragging');
  });

  window.addEventListener('mousemove', event => {
    if (!dragging) {
      return;
    }
    const rect = svg.getBoundingClientRect();
    const deltaX = (event.clientX - lastX) / rect.width * vb.w;
    const deltaY = (event.clientY - lastY) / rect.height * vb.h;
    vb.x -= deltaX;
    vb.y -= deltaY;
    lastX = event.clientX;
    lastY = event.clientY;
    applyVB();
  });

  window.addEventListener('mouseup', () => {
    dragging = false;
    cont.classList.remove('dragging');
  });

  svg.addEventListener('mousemove', event => {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const svgPoint = point.matrixTransform(svg.getScreenCTM().inverse());
    const worldX = svgPoint.x;
    const worldY = flipOffset - svgPoint.y;
    coord.textContent = `x: ${worldX.toFixed(2)}  y: ${worldY.toFixed(2)}`;
  });

  window.resetView = () => {
    vb = { ...VB0 };
    applyVB();
  };

  window.zoomIn = () => {
    vb.x += vb.w * 0.15;
    vb.y += vb.h * 0.15;
    vb.w *= 0.7;
    vb.h *= 0.7;
    applyVB();
  };

  window.zoomOut = () => {
    vb.x -= vb.w * 0.2;
    vb.y -= vb.h * 0.2;
    vb.w *= 1.4;
    vb.h *= 1.4;
    applyVB();
  };

  applyVB();

  const vertices = document.querySelectorAll('.vertex');
  vertices.forEach(vertex => {
    vertex.addEventListener('mouseenter', () => {
      const worldX = Number(vertex.getAttribute('cx'));
      const worldY = Number(vertex.getAttribute('cy'));
      showMergeRadius(worldX, worldY);
    });

    vertex.addEventListener('mouseleave', () => {
      hideMergeRadius();
    });
  });

  const legend = document.getElementById('legend');
  const seenNames = new Set();
  const labelElements = document.querySelectorAll('#labels .poly-label');

  labelElements.forEach(label => {
    const color = label.getAttribute('fill');
    const rawText = label.textContent;
    const name = rawText.replace(/_\d+$/, '');
    if (seenNames.has(name)) {
      return;
    }
    seenNames.add(name);
    const item = document.createElement('div');
    item.className = 'legend-item';
    item.innerHTML = `<span class="legend-swatch" style="background:${color}"></span>${name}`;
    legend.appendChild(item);
  });
})();
