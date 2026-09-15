import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const directory = dirname(fileURLToPath(import.meta.url));
const logo = readFileSync(join(directory, 'logo.svg'), 'utf8');
const definitions = logo.match(/<defs>([\s\S]*?)<\/defs>/)[1];
const artwork = logo.match(/  <g fill="currentColor"[\s\S]*?<\/g>/)[0];
const mark = (x, y, size, color = '#111111') =>
  `<use href="#mark" x="${x}" y="${y}" width="${size}" height="${size}" color="${color}"/>`;

const construction = `
  <g fill="none" stroke="#408b91" stroke-width="0.7">
    <circle cx="156" cy="128" r="90"/>
    <circle cx="145" cy="202" r="126"/>
    <circle cx="145" cy="202" r="114"/>
    <circle cx="65" cy="174" r="90"/>
    <circle cx="65" cy="-98" r="207.162"/>
    <circle cx="122" cy="111" r="10"/>
    <path stroke-dasharray="2 3" d="M 156 20 V 234 M 20 128 H 250 M 145 64 V 246 M 32 202 H 250"/>
    <path d="M 152 128 H 160 M 156 124 V 132 M 141 202 H 149 M 145 198 V 206 M 61 174 H 69 M 65 170 V 178"/>
  </g>`;

const board = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="780" viewBox="0 0 1200 780">
  <defs>${definitions}<symbol id="mark" viewBox="0 0 256 256">${artwork}</symbol>
    <clipPath id="construction-window"><rect width="256" height="256"/></clipPath>
  </defs>
  <rect width="1200" height="780" fill="#f4f3f0"/>
  <g font-family="-apple-system, BlinkMacSystemFont, Helvetica Neue, Arial, sans-serif" fill="#111111">
    <text x="40" y="54" font-size="26" font-weight="650">COURser / 几何鸟头</text>
    <text x="40" y="86" font-size="15" fill="#666666">走鸻参考 · 圆与圆弧构造 · 单色 SVG 审核稿</text>
    <rect x="40" y="116" width="352" height="350" rx="16" fill="white"/>
    <rect x="424" y="116" width="352" height="350" rx="16" fill="#17191b"/>
    <rect x="808" y="116" width="352" height="350" rx="16" fill="white"/>
    ${mark(60, 127, 312)}
    ${mark(444, 127, 312, '#ffffff')}
    <g transform="translate(828 127) scale(1.21875)" clip-path="url(#construction-window)">
      <use href="#mark" width="256" height="256" opacity="0.14"/>
      ${construction}
    </g>
    <text x="60" y="445" font-size="13" fill="#777777">01 / 正形</text>
    <text x="444" y="445" font-size="13" fill="#bbbbbb">02 / 反白</text>
    <text x="828" y="445" font-size="13" fill="#777777">03 / 实际构造圆</text>
    <text x="40" y="518" font-size="17" font-weight="600">小尺寸检查</text>
    <text x="40" y="544" font-size="13" fill="#666666">下方按 SVG 标称尺寸绘制；图片缩放会影响显示大小。</text>
    <rect x="40" y="568" width="540" height="126" rx="14" fill="white"/>
    <rect x="604" y="568" width="556" height="126" rx="14" fill="#17191b"/>
    ${[16, 24, 32, 48].map((size, i) => {
      const center = 104 + i * 130;
      return `${mark(center - size / 2, 614 - size / 2, size)}
        <text x="${center}" y="670" font-size="12" text-anchor="middle" fill="#777777">${size} px</text>
        ${mark(center + 566 - size / 2, 614 - size / 2, size, '#ffffff')}
        <text x="${center + 566}" y="670" font-size="12" text-anchor="middle" fill="#bbbbbb">${size} px</text>`;
    }).join('')}
    <text x="40" y="744" font-size="13" fill="#666666">头部 R90 · 眼睛 R10 · 眉纹同心圆 R126 / R114 · 喙由两段圆弧围成</text>
  </g>
</svg>`;
writeFileSync(join(directory, 'review.svg'), board);

const standaloneConstruction = `<svg xmlns="http://www.w3.org/2000/svg" width="768" height="768" viewBox="0 0 256 256">
  <rect width="256" height="256" fill="white"/>
  <defs>${definitions}</defs><g opacity="0.14">${artwork}</g>${construction}
</svg>`;
writeFileSync(join(directory, 'construction.svg'), standaloneConstruction);
