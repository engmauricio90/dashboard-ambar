(() => {
  const header = document.querySelector('[data-public-header]');
  const toggle = document.querySelector('[data-nav-toggle]');
  const menu = document.querySelector('[data-nav-menu]');
  const actions = document.querySelector('.nav-actions');
  const leadForm = document.querySelector('[data-lead-form]');
  const checkoutForm = document.querySelector('[data-checkout-form]');
  const cookieBanner = document.querySelector('[data-cookie-banner]');
  const cookieAccept = document.querySelector('[data-cookie-accept]');
  const cookieReject = document.querySelector('[data-cookie-reject]');
  const pricing = document.querySelector('[data-pricing]');
  const acquisitionKeys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'fbclid'];
  const storageKey = 'estribo_first_touch';
  const consentKey = 'estribo_cookie_consent';

  const onScroll = () => {
    if (header) {
      header.classList.toggle('is-scrolled', window.scrollY > 8);
    }
  };

  const readFirstTouch = () => {
    try {
      return JSON.parse(window.sessionStorage.getItem(storageKey) || '{}');
    } catch (error) {
      return {};
    }
  };

  const writeFirstTouch = (data) => {
    try {
      window.sessionStorage.setItem(storageKey, JSON.stringify(data));
    } catch (error) {
      // Storage pode estar indisponivel; o formulario ainda funciona sem UTM.
    }
  };

  const captureFirstTouch = () => {
    const params = new URLSearchParams(window.location.search);
    const current = readFirstTouch();
    let changed = false;

    acquisitionKeys.forEach((key) => {
      if (!current[key] && params.get(key)) {
        current[key] = params.get(key);
        changed = true;
      }
    });

    if (!current.landing_path) {
      current.landing_path = `${window.location.pathname}${window.location.search}`;
      changed = true;
    }

    if (changed) {
      writeFirstTouch(current);
    }

    return current;
  };

  const fillAcquisitionFields = () => {
    const data = captureFirstTouch();
    [...acquisitionKeys, 'landing_path'].forEach((key) => {
      [leadForm, checkoutForm].forEach((form) => {
        const field = form?.querySelector(`[name="${key}"]`);
        if (field && data[key]) field.value = data[key];
      });
    });
  };

  const setBillingPreference = (period) => {
    if (!period || !leadForm) {
      return;
    }
    const field = leadForm.querySelector('[name="billing_preference"]');
    if (field) {
      field.value = period;
    }
  };

  const setupPricing = () => {
    if (!pricing) {
      return;
    }
    const price = pricing.querySelector('[data-period-price]');
    const suffix = pricing.querySelector('[data-period-suffix]');
    const equivalent = pricing.querySelector('[data-period-equivalent]');
    const installments = pricing.querySelector('[data-period-installments]');
    const saving = pricing.querySelector('[data-period-saving]');
    const buttons = pricing.querySelectorAll('[data-period-option]');

    const selectPeriod = (button) => {
      buttons.forEach((item) => {
        const selected = item === button;
        item.classList.toggle('is-active', selected);
        item.setAttribute('aria-pressed', String(selected));
      });
      if (price) price.textContent = button.dataset.price || '';
      if (suffix) suffix.textContent = button.dataset.suffix || '';
      if (equivalent) equivalent.textContent = button.dataset.equivalent || '';
      if (installments) installments.textContent = button.dataset.installments || '';
      if (saving) {
        saving.textContent = button.dataset.saving || '';
        saving.hidden = !button.dataset.saving;
      }
      setBillingPreference(button.dataset.periodOption);
      document.querySelectorAll('[data-checkout-cta]').forEach((link) => {
        const url = new URL(link.href, window.location.origin);
        url.searchParams.set('periodo', (button.dataset.periodOption || 'ANUAL').toLowerCase());
        const acquisition = readFirstTouch();
        acquisitionKeys.forEach((key) => { if (acquisition[key]) url.searchParams.set(key, acquisition[key]); });
        link.href = url.toString();
      });
    };

    buttons.forEach((button) => {
      button.addEventListener('click', () => selectPeriod(button));
    });

    const field = leadForm?.querySelector('[name="billing_preference"]');
    const initialPeriod = field?.value || pricing.dataset.defaultPeriod;
    const active = pricing.querySelector(`[data-period-option="${initialPeriod}"]`) || pricing.querySelector('.period-button.is-active') || buttons[0];
    if (active) {
      selectPeriod(active);
    }
  };

  const track = (eventName, payload = {}) => {
    if (!eventName) {
      return;
    }
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({ event: eventName, ...payload });
    if (typeof window.gtag === 'function') {
      window.gtag('event', eventName, payload);
    }
    if (typeof window.fbq === 'function') {
      window.fbq('trackCustom', eventName, payload);
    }
  };

  const loadScript = (src, id) => {
    if (!src || document.getElementById(id)) {
      return;
    }
    const script = document.createElement('script');
    script.async = true;
    script.src = src;
    script.id = id;
    document.head.appendChild(script);
  };

  const enableAnalytics = () => {
    const { ga4Id, googleAdsId, metaPixelId } = document.body.dataset;
    if (ga4Id || googleAdsId) {
      const gtagId = ga4Id || googleAdsId;
      loadScript(`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(gtagId)}`, 'estribo-gtag');
      window.dataLayer = window.dataLayer || [];
      window.gtag = window.gtag || function gtag(){ window.dataLayer.push(arguments); };
      window.gtag('js', new Date());
      if (ga4Id) {
        window.gtag('config', ga4Id);
      }
      if (googleAdsId) {
        window.gtag('config', googleAdsId);
      }
    }
    if (metaPixelId) {
      window.fbq = window.fbq || function fbq(){ (window.fbq.callMethod ? window.fbq.callMethod : window.fbq.queue.push).apply(window.fbq, arguments); };
      window.fbq.queue = window.fbq.queue || [];
      window.fbq.loaded = true;
      window.fbq.version = '2.0';
      loadScript('https://connect.facebook.net/en_US/fbevents.js', 'estribo-meta-pixel');
      window.fbq('init', metaPixelId);
      window.fbq('track', 'PageView');
    }
  };

  const setupCookieConsent = () => {
    if (!cookieBanner) {
      return;
    }
    const consent = window.localStorage.getItem(consentKey);
    if (consent === 'accepted') {
      enableAnalytics();
      return;
    }
    if (consent === 'rejected') {
      return;
    }
    cookieBanner.hidden = false;
    cookieAccept?.addEventListener('click', () => {
      window.localStorage.setItem(consentKey, 'accepted');
      cookieBanner.hidden = true;
      enableAnalytics();
    });
    cookieReject?.addEventListener('click', () => {
      window.localStorage.setItem(consentKey, 'rejected');
      cookieBanner.hidden = true;
    });
  };

  if (toggle && menu && actions) {
    toggle.addEventListener('click', () => {
      const isOpen = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!isOpen));
      menu.classList.toggle('is-open', !isOpen);
      actions.classList.toggle('is-open', !isOpen);
    });
  }

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    document.querySelectorAll('.reveal').forEach((element) => observer.observe(element));
  } else {
    document.querySelectorAll('.reveal').forEach((element) => element.classList.add('is-visible'));
  }

  document.querySelectorAll('[data-track]').forEach((element) => {
    element.addEventListener('click', () => {
      if (element.dataset.billingCta !== undefined) {
        const active = pricing?.querySelector('.period-button.is-active');
        setBillingPreference(active?.dataset.periodOption || pricing?.dataset.defaultPeriod);
      }
      track(element.dataset.track);
    });
  });

  document.querySelectorAll('[data-track-view]').forEach((element) => {
    track(element.dataset.trackView);
  });

  if (leadForm) {
    let started = false;
    leadForm.addEventListener('input', () => {
      if (!started) {
        started = true;
        track('demo_form_start');
      }
    }, { once: true });
    leadForm.addEventListener('submit', () => track('demo_form_submit'));
  }

  if (checkoutForm) {
    let checkoutStarted = false;
    checkoutForm.addEventListener('input', () => {
      if (!checkoutStarted) {
        checkoutStarted = true;
        track('checkout_form_start');
      }
    });
    checkoutForm.addEventListener('submit', () => {
      track('checkout_form_submit');
      track('checkout_redirect');
    });
    const periodField = checkoutForm.querySelector('[name="periodicidade"]');
    const updateSummary = () => {
      document.querySelectorAll('[data-checkout-summary]').forEach((summary) => {
        summary.hidden = summary.dataset.checkoutSummary !== periodField?.value;
      });
    };
    periodField?.addEventListener('change', updateSummary);
    updateSummary();
  }

  fillAcquisitionFields();
  setupPricing();
  setupCookieConsent();
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });
})();
