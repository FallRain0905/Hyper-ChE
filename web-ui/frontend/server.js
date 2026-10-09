// @ts-expect-error
const Koa = require('koa');
const path = require('path');
const fs = require('fs');
const serve = require('koa-static');
const app = new Koa();


const home = serve(path.join(__dirname) + '/dist/', {
    gzip: true,
});

app.use(async (ctx, next) => {
    console.log(new Date(), ctx.request.url);
    await next();
})

// The research report is the public homepage. The functional React workspace
// has a separate document URL so its hash routes do not replace report chapters.
app.use(async (ctx, next) => {
    if (ctx.method !== 'GET' && ctx.method !== 'HEAD') return next();
    const file = ctx.path === '/' ? 'report/hyperche-demo.html'
        : ctx.path === '/workspace/' ? 'index.html' : null;
    if (ctx.path === '/workspace') {
        ctx.redirect('/workspace/');
        return;
    }
    if (!file) return next();
    ctx.type = 'html';
    ctx.set('Cache-Control', 'no-cache');
    ctx.body = fs.createReadStream(path.join(__dirname, 'dist', file));
});

app.use(home);
app.listen(5000);
console.log('server is running at http://localhost:5000');
