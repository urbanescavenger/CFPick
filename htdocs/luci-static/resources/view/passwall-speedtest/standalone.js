'use strict';
'require view';
'require poll';
'require rpc';

const callStatus = rpc.declare({
	object: 'passwall-speedtest',
	method: 'standalone_status',
	expect: {}
});

const callStart = rpc.declare({
	object: 'passwall-speedtest',
	method: 'standalone_start',
	expect: {}
});

const callStop = rpc.declare({
	object: 'passwall-speedtest',
	method: 'standalone_stop',
	expect: {}
});

const callEnable = rpc.declare({
	object: 'passwall-speedtest',
	method: 'standalone_enable',
	expect: {}
});

const callDisable = rpc.declare({
	object: 'passwall-speedtest',
	method: 'standalone_disable',
	expect: {}
});

function consoleUrl(status) {
	const web = (status && status.web) || {};
	const port = web.port || 0;
	if (!port)
		return '';

	const host = window.location.hostname.indexOf(':') >= 0
		? '[' + window.location.hostname + ']' : window.location.hostname;
	const token = web.token ? '?token=' + encodeURIComponent(web.token) : '';

	return 'http://' + host + ':' + port + '/' + token;
}

function coreLabel(engine) {
	const type = (engine && engine.core_type) || '';
	const cores = (engine && engine.cores) || {};
	const info = cores[type] || {};
	if (!type)
		return _('未检测');
	const version = info.version ? ' · ' + info.version : '';
	const state = info.installed ? _('已安装') : _('未安装');
	return type + ' · ' + state + version;
}

return view.extend({
	load: function() {
		return callStatus();
	},

	render: function(status) {
		const serviceState = E('span');
		const engineState = E('span');
		const coreState = E('span');
		const bestState = E('span');
		const linkState = E('span');
		const message = E('p', { 'class': 'muted' });

		const openButton = E('button', {
			type: 'button',
			'class': 'btn cbi-button cbi-button-apply'
		}, _('打开独立操作台'));

		const enableButton = E('button', {
			type: 'button',
			'class': 'btn cbi-button cbi-button-apply'
		}, _('启用并启动'));

		const startButton = E('button', {
			type: 'button',
			'class': 'btn cbi-button cbi-button-action'
		}, _('启动'));

		const stopButton = E('button', {
			type: 'button',
			'class': 'btn cbi-button cbi-button-reset'
		}, _('停止'));

		const disableButton = E('button', {
			type: 'button',
			'class': 'btn cbi-button cbi-button-reset'
		}, _('停用'));

		let latest = status;

		const paint = (st) => {
			st = st || {};
			latest = st;
			const engine = st.engine || {};
			const web = st.web || {};
			const url = consoleUrl(st);

			serviceState.replaceChildren(
				E('b', { style: 'color:%s'.format(st.service_running ? 'green' : 'red') },
					st.service_running ? _('运行中') : _('已停止')),
				' · ',
				st.service_enabled ? _('开机自启') : _('未设开机自启')
			);

			engineState.replaceChildren(
				E('b', { style: 'color:%s'.format(engine.running ? 'green' : 'gray') },
					engine.running ? _('测速运行中') : _('空闲')),
				engine.phase ? ' · ' + engine.phase : ''
			);

			coreState.replaceChildren(coreLabel(engine));
			bestState.replaceChildren(engine.best_ip || '-');

			// A loopback-only console cannot be opened from the LuCI browser.
			const listen = web.listen || '';
			const loopback = !listen || listen === '127.0.0.1'
				|| listen === 'localhost' || listen === '::1';
			linkState.replaceChildren(url
				? E([], [ E('code', {}, url),
					loopback ? ' (' + _('仅监听本机，需改 web.listen') + ')' : '' ])
				: _('不可用'));

			openButton.disabled = !url || !st.service_running || loopback;
			startButton.disabled = !!st.service_running;
			stopButton.disabled = !st.service_running;
			enableButton.disabled = !!st.service_enabled;
			disableButton.disabled = !st.service_enabled;
		};

		const refresh = () => callStatus().then(paint).catch(function() {});

		const run = (fn, label) => function() {
			message.replaceChildren(_('正在执行：') + label + '…');
			fn().then(function(r) {
				r = r || {};
				if (r.code !== 0)
					message.replaceChildren(E('b', { style: 'color:red' },
						label + _('失败') + (r.output ? ': ' + r.output : '')));
				else
					message.replaceChildren(label + _('完成'));
				return refresh();
			}).catch(function(err) {
				message.replaceChildren(E('b', { style: 'color:red' }, String(err)));
			});
		};

		openButton.addEventListener('click', function() {
			const url = consoleUrl(latest);
			if (url)
				window.open(url, '_blank');
		});
		enableButton.addEventListener('click', run(callEnable, _('启用并启动')));
		startButton.addEventListener('click', run(callStart, _('启动')));
		stopButton.addEventListener('click', run(callStop, _('停止')));
		disableButton.addEventListener('click', run(callDisable, _('停用')));

		paint(status);
		poll.add(refresh, 5);

		return E([], [
			E('h2', {}, _('独立测速（自带上游内核）')),
			E('div', { 'class': 'cbi-section' }, [
				E('p', { 'class': 'cbi-section-descr' },
					_('不经过 PassWall 的 run_socks：本机 mihomo / Xray-core 直接拉起候选 IP 的本地 SOCKS，并用 mark 255 避开 PassWall 对本机出站的二次代理。节点以分享链接维护，结果只导出 CSV/JSON，不改 PassWall 节点。')),
				E('div', { 'class': 'cbi-section' }, [
					E('p', {}, [ E('strong', {}, _('操作台服务') + ': '), serviceState ]),
					E('p', {}, [ E('strong', {}, _('测速状态') + ': '), engineState ]),
					E('p', {}, [ E('strong', {}, _('当前内核') + ': '), coreState ]),
					E('p', {}, [ E('strong', {}, _('最优 IP') + ': '), bestState ]),
					E('p', {}, [ E('strong', {}, _('操作台地址') + ': '), linkState ]),
					E('p', {}, [ enableButton, ' ', startButton, ' ', stopButton, ' ', disableButton, ' ', openButton ]),
					message,
					E('p', { 'class': 'muted' },
						_('节点、IP 列表、内核切换与定时任务都在独立操作台里维护。服务未启动时无法打开操作台；token 会自动附加到链接。'))
				])
			])
		]);
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
