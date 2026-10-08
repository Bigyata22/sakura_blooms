document.addEventListener('DOMContentLoaded', () => {
	const periodForm = document.querySelector('[data-period-form]');
	if (periodForm) {
		const startDate = periodForm.elements.start_date;
		const endDate = periodForm.elements.end_date;
		const syncEndDate = () => {
			endDate.min = startDate.value;
			if (endDate.value && startDate.value && endDate.value < startDate.value) {
				endDate.value = startDate.value;
			}
		};
		startDate.addEventListener('change', syncEndDate);
		syncEndDate();
		periodForm.addEventListener('submit', (event) => {
			if (startDate.value && endDate.value && endDate.value < startDate.value) {
				event.preventDefault();
				endDate.setCustomValidity('The end date must be on or after the start date.');
				endDate.reportValidity();
			}
		});
		endDate.addEventListener('input', () => endDate.setCustomValidity(''));
	}

	document.querySelectorAll('form[data-confirm]').forEach((form) => {
		form.addEventListener('submit', (event) => {
			if (!window.confirm(form.dataset.confirm)) event.preventDefault();
		});
	});

	const notificationToggle = document.querySelector('[data-notification-toggle]');
	if (notificationToggle) {
		notificationToggle.addEventListener('change', async () => {
			if (!notificationToggle.checked || !('Notification' in window)) return;
			try {
				const permission = await Notification.requestPermission();
				if (permission !== 'granted') notificationToggle.checked = false;
			} catch {
				notificationToggle.checked = false;
			}
		});
	}

	const schedule = document.querySelector('#cycle-reminder-schedule');
	if (schedule?.dataset.enabled === '1' && 'Notification' in window && Notification.permission === 'granted') {
		const storageKey = `sakura-blooms-reminder-${schedule.dataset.periodDate}`;
		const reminderAt = new Date(`${schedule.dataset.reminderDate}T09:00:00`);
		const periodEnds = new Date(`${schedule.dataset.periodDate}T23:59:59`);
		const notifyWhenDue = () => {
			const now = new Date();
			if (now >= reminderAt && now <= periodEnds && !localStorage.getItem(storageKey)) {
				const days = Number(schedule.dataset.daysBefore);
				const timing = days === 1 ? 'tomorrow' : `in ${days} days`;
				new Notification('A gentle note from Sakura Blooms', {
					body: `Your next period is estimated around ${schedule.dataset.periodDate}. It may be approaching ${timing}. Take care of yourself, and update your tracker when you’re ready.`,
					tag: storageKey,
				});
				localStorage.setItem(storageKey, 'shown');
			}
		};
		const delay = reminderAt.getTime() - Date.now();
		if (delay > 0) window.setTimeout(notifyWhenDue, delay);
		notifyWhenDue();
	}
});
