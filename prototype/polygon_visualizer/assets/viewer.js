(function() {
  const svg = document.getElementById('canvas');
  const cont = document.getElementById('svg-container');
  const info = document.getElementById('zoom-info');
  const coord = document.getElementById('coords');
  const hoverOverlay = document.getElementById('hover-overlay');

  const VB0 = { ...window.__VIZ_DATA__.vb };
  let vb = { ...VB0 };
  const flipOffset = window.__VIZ_DATA__.flipOffset;
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
      const layerIndex = Number(label.dataset.layer || 0);
      const offset = layerIndex * fontSize * 2;

      label.setAttribute('font-size', String(fontSize));
      label.setAttribute('y', String(baseY - offset));
    });

    const vertices = document.querySelectorAll('.vertex');
    vertices.forEach(vertex => {
      const baseRadius = Number(vertex.dataset.baseR || 3);
      const radius = zoom >= 1 ? baseRadius / zoom : baseRadius;
      vertex.setAttribute('r', String(radius));
    });
  }

  function computeGridStep(viewWidth, viewHeight) {
    const targetLines = 12;
    const rawStep = Math.max(viewWidth, viewHeight) / targetLines;
    const power = Math.floor(Math.log10(rawStep));
    const base = 10 ** power;

    if (rawStep / base > 5) {
      return 10 * base;
    }
    if (rawStep / base > 2) {
      return 5 * base;
    }
    if (rawStep / base > 1) {
      return 2 * base;
    }
    return base;
  }

  function computeGridYLines(viewTop, viewHeight, currentFlipOffset, step) {
    const mathYMin = currentFlipOffset - (viewTop + viewHeight);
    const mathYMax = currentFlipOffset - viewTop;
    const yStart = Math.floor(mathYMin / step) * step;
    const yEnd = Math.ceil(mathYMax / step) * step;

    const lines = [];
    const count = Math.round((yEnd - yStart) / step);

    for (let index = 0; index <= count; index += 1) {
      const mathY = yStart + index * step;
      const svgY = currentFlipOffset - mathY;
      lines.push({ mathY, svgY });
    }

    return lines;
  }

  function getVisibleViewportMetrics() {
    const rect = svg.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;

    if (width <= 0 || height <= 0) {
      return {
        top: vb.y,
        left: vb.x,
        right: vb.x + vb.w,
        bottom: vb.y + vb.h,
        unitPerPixelX: 1,
        unitPerPixelY: 1,
      };
    }

    const viewAspect = vb.w / vb.h;
    const rectAspect = width / height;
    let renderWidth = width;
    let renderHeight = height;
    let offsetLeft = 0;
    let offsetTop = 0;

    if (rectAspect > viewAspect) {
      renderWidth = height * viewAspect;
      offsetLeft = (width - renderWidth) / 2;
    } else {
      renderHeight = width / viewAspect;
      offsetTop = (height - renderHeight) / 2;
    }

    const ctm = svg.getScreenCTM();
    if (!ctm) {
      return {
        top: vb.y,
        left: vb.x,
        right: vb.x + vb.w,
        bottom: vb.y + vb.h,
        unitPerPixelX: vb.w / renderWidth,
        unitPerPixelY: vb.h / renderHeight,
      };
    }

    const inverse = ctm.inverse();
    const point = svg.createSVGPoint();

    point.x = rect.left + offsetLeft;
    point.y = rect.top + offsetTop;
    const topLeft = point.matrixTransform(inverse);

    point.x = rect.left + offsetLeft + renderWidth;
    point.y = rect.top + offsetTop + renderHeight;
    const bottomRight = point.matrixTransform(inverse);

    return {
      top: topLeft.y,
      left: topLeft.x,
      right: bottomRight.x,
      bottom: bottomRight.y,
      unitPerPixelX: (bottomRight.x - topLeft.x) / renderWidth,
      unitPerPixelY: (bottomRight.y - topLeft.y) / renderHeight,
    };
  }

  function drawGrid() {
    const grid = document.getElementById('grid');
    grid.innerHTML = '';

    const labelsGroup = document.getElementById('grid-labels');
    labelsGroup.innerHTML = '';

    const viewport = getVisibleViewportMetrics();
    const edgeOffsetX = 6 * viewport.unitPerPixelX;
    const edgeOffsetY = 6 * viewport.unitPerPixelY;
    const gridLabelFontSize = 12 * viewport.unitPerPixelY;

    const gridStep = computeGridStep(vb.w, vb.h);
    const overscanFactor = 10;

    const gridMinX = vb.x - vb.w * overscanFactor;
    const gridMaxX = vb.x + vb.w + vb.w * overscanFactor;
    const gridMinY = vb.y - vb.h * overscanFactor;
    const gridMaxY = vb.y + vb.h + vb.h * overscanFactor;

    const mathGridYMin = flipOffset - gridMaxY;
    const mathGridYMax = flipOffset - gridMinY;
    const gridYLines = computeGridYLines(gridMinY, gridMaxY - gridMinY, flipOffset, gridStep);

    const xStart = Math.floor(gridMinX / gridStep) * gridStep;
    const xEnd = Math.ceil(gridMaxX / gridStep) * gridStep;

    for (let gridX = xStart; gridX <= xEnd; gridX += gridStep) {
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', String(gridX));
      line.setAttribute('y1', String(mathGridYMin));
      line.setAttribute('x2', String(gridX));
      line.setAttribute('y2', String(mathGridYMax));
      line.setAttribute('class', 'grid-line');
      grid.appendChild(line);
    }

    for (const gridYLine of gridYLines) {
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', String(gridMinX));
      line.setAttribute('y1', String(gridYLine.mathY));
      line.setAttribute('x2', String(gridMaxX));
      line.setAttribute('y2', String(gridYLine.mathY));
      line.setAttribute('class', 'grid-line');
      grid.appendChild(line);

      // Y-подпись: по той же логике, что X-подписи. Позиция по X = vb.x + edgeOffsetX
      // (левая граница viewBox), диапазон по Y уже покрывает весь viewBox через overscan.
      if (gridYLine.svgY >= vb.y && gridYLine.svgY <= vb.y + vb.h) {
        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('x', String(viewport.left - 430 * viewport.unitPerPixelX));
        label.setAttribute('y', String(gridYLine.svgY));
        label.setAttribute('font-size', String(gridLabelFontSize));
        label.setAttribute('fill', '#000');
        label.setAttribute('class', 'grid-label');
        label.setAttribute('text-anchor', 'start');
        label.setAttribute('dominant-baseline', 'middle');
        label.textContent = gridYLine.mathY.toFixed(0);
        labelsGroup.appendChild(label);
      }
    }

    // X-подписи: диапазон по всему viewBox, чтобы тянулись до краёв окна;
    // по вертикали прижимаем к vb.y + edgeOffsetY (как в исходной рабочей версии).
    const labelXStart = Math.floor((vb.x - vb.w) / gridStep) * gridStep;
    const labelXEnd = Math.ceil((vb.x + vb.w + vb.w) / gridStep) * gridStep;

    for (let gridX = labelXStart; gridX <= labelXEnd; gridX += gridStep) {
      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', String(gridX + edgeOffsetX));
      label.setAttribute('y', String(vb.y + edgeOffsetY));
      label.setAttribute('font-size', String(gridLabelFontSize));
      label.setAttribute('fill', '#000');
      label.setAttribute('class', 'grid-label');
      label.setAttribute('text-anchor', 'start');
      label.setAttribute('dominant-baseline', 'hanging');
      label.textContent = gridX.toFixed(0);
      labelsGroup.appendChild(label);
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

    const screenMatrix = svg.getScreenCTM();
    if (!screenMatrix) {
      return;
    }

    const svgPoint = point.matrixTransform(screenMatrix.inverse());
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

  const LAYER_BEFORE_ID = 'layer-0';
  const LAYER_AFTER_ID = 'layer-1';

  function setLayerVisible(layerId, visible) {
    const group = document.getElementById(layerId);
    if (group) {
      group.setAttribute('data-visible', visible ? 'true' : 'false');
    }

    // Лейблы связаны со слоем через data-layer (0 для before, 1 для after)
    const layerIndex = layerId === LAYER_BEFORE_ID ? '0' : '1';
    const labels = document.querySelectorAll(`.poly-label[data-layer="${layerIndex}"]`);
    labels.forEach(label => {
      label.setAttribute('data-visible', visible ? 'true' : 'false');
    });
  }

  function applyViewMode(mode) {
    if (mode === 'before') {
      setLayerVisible(LAYER_BEFORE_ID, true);
      setLayerVisible(LAYER_AFTER_ID, false);
    } else if (mode === 'after') {
      setLayerVisible(LAYER_BEFORE_ID, false);
      setLayerVisible(LAYER_AFTER_ID, true);
    } else {
      setLayerVisible(LAYER_BEFORE_ID, true);
      setLayerVisible(LAYER_AFTER_ID, true);
    }
  }

  const toggleButtons = document.querySelectorAll('#view-toggle button');
  toggleButtons.forEach(button => {
    button.addEventListener('click', () => {
      const mode = button.dataset.viewMode;
      toggleButtons.forEach(other => other.classList.remove('active'));
      button.classList.add('active');
      applyViewMode(mode);
    });
  });

  // Начальный режим — как у кнопки с классом .active в разметке (по умолчанию "after")
  const initialActive = document.querySelector('#view-toggle button.active');
  if (initialActive) {
    applyViewMode(initialActive.dataset.viewMode);
  }

})();