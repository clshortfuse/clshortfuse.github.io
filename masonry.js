const archive = document.querySelector('.archive');
const cards = [...archive.querySelectorAll('.card')];
let frame;

function layout() {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(() => {
    const gutter = Number.parseFloat(getComputedStyle(archive).columnGap);
    const heights = cards.map(card => Math.ceil(card.getBoundingClientRect().height + gutter));
    archive.classList.add('masonry');
    cards.forEach((card, index) => { card.style.gridRowEnd = `span ${heights[index]}`; });
  });
}

const observer = new ResizeObserver(layout);
cards.forEach(card => observer.observe(card));
layout();
