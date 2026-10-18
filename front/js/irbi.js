let uid = 0;

export function irbiSvg(state = "idle", label = "Ирби") {
  const id = `irbi-${++uid}`;
  return `
<svg class="irbi" data-state="${state}" viewBox="0 0 120 120" role="img" aria-label="${label}">
  <defs>
    <clipPath id="${id}-hole">
      <path d="M0 0H120V88H110A50 12 0 0 1 10 88H0Z"/>
    </clipPath>
  </defs>
  <ellipse class="irbi-pit" cx="60" cy="88" rx="48" ry="10.5"/>
  <path class="irbi-ring" d="M10 88A50 12 0 0 1 110 88"/>
  <g clip-path="url(#${id}-hole)">
    <g class="irbi-body">
      <g class="irbi-ear irbi-ear--left" style="transform-origin:53px 70px">
        <ellipse cx="49" cy="42" rx="8.5" ry="28" transform="rotate(-9 49 42)"/>
      </g>
      <g class="irbi-ear irbi-ear--right" style="transform-origin:69px 70px">
        <ellipse cx="78" cy="46" rx="8" ry="25" transform="rotate(24 78 46)"/>
      </g>
      <g class="irbi-head" style="transform-origin:60px 96px">
        <ellipse class="irbi-skin" cx="60" cy="88" rx="28" ry="26"/>
        <g class="irbi-face">
          <g class="irbi-eyes" style="transform-origin:60px 80px">
            <ellipse class="irbi-eye" cx="49.5" cy="80" rx="4.2" ry="5.8"/>
            <ellipse class="irbi-eye" cx="70.5" cy="80" rx="4.2" ry="5.8"/>
            <path class="irbi-glint" d="M47.5 78.2l3.4-1.6-0.6 2.6z"/>
            <path class="irbi-glint" d="M68.5 78.2l3.4-1.6-0.6 2.6z"/>
          </g>
          <path class="irbi-nose" d="M56.6 89.5h6.8l-2.1 3.2a1.5 1.5 0 0 1-2.6 0z"/>
        </g>
      </g>
    </g>
  </g>
  <path class="irbi-ring" d="M10 88A50 12 0 0 0 110 88"/>
</svg>`;
}

export function setIrbiState(container, state) {
  container?.querySelectorAll(".irbi").forEach(svg => {
    svg.dataset.state = state;
  });
}

export function irbiAvatar(state = "idle", size = "sm") {
  const box = document.createElement("div");
  box.className = `irbi-avatar irbi-avatar--${size}`;
  box.innerHTML = irbiSvg(state);
  return box;
}

export function createTyper(target, { onTick } = {}) {
  let queue = "";
  let raf = 0;
  let resolveIdle = null;

  function step() {
    if (!queue) {
      raf = 0;
      resolveIdle?.();
      resolveIdle = null;
      return;
    }
    const take = Math.max(1, Math.ceil(queue.length / 45));
    target.textContent += queue.slice(0, take);
    queue = queue.slice(take);
    onTick?.();
    raf = requestAnimationFrame(step);
  }

  return {
    push(text) {
      queue += text;
      if (!raf) raf = requestAnimationFrame(step);
    },
    idle() {
      if (!queue && !raf) return Promise.resolve();
      return new Promise(resolve => {
        resolveIdle = resolve;
      });
    }
  };
}
