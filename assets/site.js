/* Keyboard support for existing FAQ and scrollable sections. */
(function () {
  'use strict';
  document.querySelectorAll('.faq-q').forEach(function (question, index) {
    var answer = question.parentElement.querySelector('.faq-a');
    if (!answer) return;
    answer.id = answer.id || 'faq-answer-' + index;
    question.setAttribute('role', 'button');
    question.setAttribute('tabindex', '0');
    question.setAttribute('aria-controls', answer.id);
    function sync() {
      question.setAttribute('aria-expanded', String(question.parentElement.classList.contains('open')));
    }
    sync();
    question.addEventListener('click', sync);
    question.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        question.click();
      }
    });
  });
  document.querySelectorAll('.price-table-wrap, .process-steps').forEach(function (container) {
    container.setAttribute('tabindex', '0');
    container.setAttribute('role', 'region');
    var title = container.parentElement.querySelector('h2');
    if (title) container.setAttribute('aria-label', title.textContent.trim());
  });
})();
