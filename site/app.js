const button = document.querySelector('.menu');
const links = document.querySelector('.nav-links');

if (button && links) {
  button.addEventListener('click', () => {
    const open = button.getAttribute('aria-expanded') !== 'true';
    button.setAttribute('aria-expanded', String(open));
    button.setAttribute('aria-label', open ? 'Close navigation menu' : 'Open navigation menu');
    links.classList.toggle('open', open);
  });

  links.addEventListener('click', (event) => {
    if (event.target.closest('a')) {
      links.classList.remove('open');
      button.setAttribute('aria-expanded', 'false');
      button.setAttribute('aria-label', 'Open navigation menu');
    }
  });
}
