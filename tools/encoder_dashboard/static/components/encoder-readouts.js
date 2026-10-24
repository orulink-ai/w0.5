"use strict";
/** Two read-only cards, each driven by its own measurement/freshness. */
(function(scope) {
  const PINS = ['PA0', 'PB7'];
  const LABELS = {valid:'PWM 有效',invalid:'PWM 无效',stale:'数据已超时',waiting:'等待数据',disconnected:'未连接'};
  function models(state) {
    return PINS.map((pin,index) => {
      const item = state?.encoders?.find(value => value.id === index + 1) ||
        (index === 0 ? state : null);
      const signal = !state?.connected ? 'disconnected' : item?.signal || 'waiting';
      const reading = item?.reading;
      const valid = signal === 'valid' && Number.isFinite(reading?.angle_deg);
      const fresh = ['valid','invalid'].includes(signal);
      const number = (value,digits=0) => Number.isFinite(value) ? value.toFixed(digits) : '—';
      return {id:index+1,pin,signal,label:LABELS[signal] || '状态未知',valid,
        angle:valid ? number(reading.angle_deg,2) : '—',
        angleValue:valid ? reading.angle_deg : null,
        frequency:valid ? number(reading?.frequency_hz,1) : '—',
        high:fresh ? number(reading?.high_us) : '—',
        period:fresh ? number(reading?.period_us) : '—',
        samples:item?.samples || 0,validSamples:item?.valid_samples || 0,
        age:Number.isFinite(item?.age_ms) ? `${item.age_ms} ms 前` : '尚未收到数据'};
    });
  }
  class EncoderReadouts {
    constructor(element) {
      this.element=element;
      element.innerHTML=PINS.map((pin,index)=>`
        <section class="encoder-card card" data-encoder="${index+1}" aria-label="编码器${index+1} ${pin}">
          <div class="angle-heading"><div><div class="section-label">编码器${index===0?'①':'②'} · ${pin}</div>
            <p>AS5600 PWM · 单圈绝对角度</p></div><span data-field="signal" class="badge">等待数据</span></div>
          <div class="encoder-angle"><strong data-field="angle">—</strong><span>°</span>
            <div class="encoder-track" aria-hidden="true"><i data-field="marker" hidden></i></div></div>
          <dl class="encoder-metrics"><div><dt>PWM 频率</dt><dd><span data-field="frequency">—</span> Hz</dd></div>
            <div><dt>高电平</dt><dd><span data-field="high">—</span> μs</dd></div>
            <div><dt>周期</dt><dd><span data-field="period">—</span> μs</dd></div></dl>
          <p class="encoder-meta"><span data-field="samples">有效 0 / 0 帧</span><span data-field="age">尚未收到数据</span></p>
        </section>`).join('');
    }
    render(state) {
      const result=models(state);
      for(const value of result) {
        const card=this.element.querySelector(`[data-encoder="${value.id}"]`);
        const field=name=>card.querySelector(`[data-field="${name}"]`);
        for(const name of ['angle','frequency','high','period','age']) field(name).textContent=value[name];
        field('signal').textContent=value.label;
        field('signal').className=`badge ${value.signal}`;
        field('samples').textContent=`有效 ${value.validSamples} / ${value.samples} 帧`;
        field('marker').hidden=!value.valid;
        if(value.valid) field('marker').style.left=`${value.angleValue / 360 * 100}%`;
      }
      return result;
    }
  }
  scope.EncoderReadouts=Object.freeze({EncoderReadouts,models});
  if(typeof module!=='undefined')module.exports=scope.EncoderReadouts;
})(globalThis);
