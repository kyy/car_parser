    // google_translate_helper.js
(() => {
  if (window.__gt_ready) return;

  // Колбэк, который вызовет google после загрузки
  window.googleTranslateElementInit = function () {
    new google.translate.TranslateElement(
      {
        pageLanguage: 'zh-CN',
        includedLanguages: 'ru',
        autoDisplay: false,
      },
      'google_translate_element'
    );
    window.__gt_ready = true;
  };

  // Подгружаем сам скрипт Google
  const s = document.createElement('script');
  s.type = 'text/javascript';
  s.src = 'https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';
  document.head.appendChild(s);

  const div = document.createElement('div');
  div.id = 'google_translate_element';
  div.style.display = 'none';
  document.body.appendChild(div);

  // Хелпер: дождаться перевода конкретного элемента
  window.__translateToRussian = () => {
    return new Promise((resolve) => {
      // Программно выбираем русский в выпадающем списке Google Element
      const trySelect = () => {
        const combo = document.querySelector('.goog-te-combo');
        if (!combo) {
          setTimeout(trySelect, 300);
          return;
        }
        combo.value = 'ru';
        combo.dispatchEvent(new Event('change', { bubbles: true }));

        // Ждём, пока Google заменит текст (проверяем, что появились кириллические символы)
        let tries = 0;
        const checker = setInterval(() => {
          tries++;
          const text = document.body.innerText;
          const hasRussian = /[а-яА-Я]/.test(text);
          if (hasRussian || tries > 40) {
            clearInterval(checker);
            resolve(hasRussian);
          }
        }, 250);
      };
      trySelect();
    });
  };
})();