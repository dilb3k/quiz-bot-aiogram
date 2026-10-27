const http = require('http');
let sequence = 0;
const polls = new Map();
http.createServer(async (req, res) => {
  const reply = (status, body) => {
    res.writeHead(status, {'Content-Type': 'application/json'});
    res.end(JSON.stringify(body));
  };
  const method = req.url.split('?')[0].split('/').pop();
  let chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString();
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    body = Object.fromEntries(new URLSearchParams(raw));
    // Aiogram sends multipart form data even without files.
    const boundary = (req.headers['content-type'] || '').match(/boundary=(.+)$/)?.[1];
    if (boundary) {
      body = {};
      for (const part of raw.split('--' + boundary)) {
        const name = part.match(/name="([^"]+)"/);
        if (name) body[name[1]] = part.split('\r\n\r\n').slice(1).join('\r\n\r\n').replace(/\r\n$/, '');
      }
    }
  }
  const unpack = v => typeof v === 'string' ? JSON.parse(v) : v;
  if (method === 'sendPoll') {
    if (String(body.chat_id) === '-429') return reply(429, {ok:false,error_code:429,description:'Too Many Requests',parameters:{retry_after:2}});
    if (String(body.chat_id) === '-403') return reply(403, {ok:false,error_code:403,description:'Forbidden: bot was kicked'});
    if (String(body.chat_id) === '-500') return reply(500, {ok:false,error_code:500,description:'Internal Server Error'});
    try {
      const options = unpack(body.options);
      const correct = unpack(body.correct_option_ids);
      if (body.type !== 'quiz' || !Array.isArray(correct) || correct.length !== 1 || !options[correct[0]] ||
          options.length < 2 || options.length > 4 || String(body.question).length > 300 ||
          Number(body.open_period) < 5 || Number(body.open_period) > 2628000) {
        return reply(400,{ok:false,error_code:400,description:'Bad Request: invalid quiz'});
      }
      const id = ++sequence;
      const poll = {id:String(id), question:body.question, options:options.map((o,i)=>({text:o.text,voter_count:0,persistent_id:String(i)})),
        total_voter_count:0,is_closed:false,is_anonymous:unpack(body.is_anonymous),type:'quiz',allows_multiple_answers:false,
        allows_revoting:false,members_only:false,correct_option_ids:correct};
      polls.set(id,poll);
      return reply(200,{ok:true,result:{message_id:id,date:Math.floor(Date.now()/1000),chat:{id:Number(body.chat_id),type:'private'},poll}});
    } catch {
      return reply(400,{ok:false,error_code:400,description:'Bad Request: invalid JSON options'});
    }
  }
  if (method === 'stopPoll') {
    const poll = polls.get(Number(body.message_id));
    if (!poll) return reply(400,{ok:false,error_code:400,description:'Bad Request: poll not found'});
    poll.is_closed = true;
    return reply(200,{ok:true,result:poll});
  }
  if (method === 'sendMessage') return reply(200,{ok:true,result:{message_id:++sequence,date:Math.floor(Date.now()/1000),chat:{id:Number(body.chat_id),type:'private'},text:body.text}});
  return reply(501,{ok:false,error_code:501,description:'Method not modelled in this local contract'});
}).listen(process.env.PORT);
