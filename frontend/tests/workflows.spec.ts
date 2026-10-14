import {test,expect} from '@playwright/test'

test('connection warning clears on recovery without masking a real operation error',async({page})=>{
  let fail=true
  await page.route('**/api/health',route=>fail?route.abort('failed'):route.continue())
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('正在自动重连',{timeout:20000})
  fail=false
  await expect(page.getByRole('alert')).toHaveCount(0,{timeout:12000})
  // A business error is independent from a recovered health probe.
  await page.route('**/api/search?**',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'检索操作测试错误'})}))
  await page.getByRole('button',{name:'设置',exact:true}).click()
  await page.getByRole('navigation').getByRole('button',{name:'课程知识库',exact:true}).click()
  await page.getByRole('button',{name:'语义检索实验'}).click()
  await page.getByRole('textbox',{name:'语义检索问题'}).fill('RAG')
  await page.getByRole('button',{name:'真实检索'}).click()
  await expect(page.getByRole('alert')).toContainText('检索操作测试错误')
  await page.waitForTimeout(5500)
  await expect(page.getByRole('alert')).toContainText('检索操作测试错误')
})

test('labels can select and deselect, manually route live chat, then restore semantic routing',async({page})=>{
  test.skip(!process.env.RUN_LIVE_TESTS,'Set RUN_LIVE_TESTS=1 and configure the model key for online checks')
  await page.goto('/')
  await page.getByRole('button',{name:'新对话',exact:true}).click()
  const tags=page.getByRole('group',{name:'选择回答工作流'})
  for(const label of ['课程知识问答','学习路径推荐','面试题训练','PRD点评','简历优化']){
    const tag=tags.getByRole('button',{name:label,exact:true})
    await tag.click()
    await expect(tag).toHaveAttribute('aria-pressed','true')
    await tag.click()
    await expect(tag).toHaveAttribute('aria-pressed','false')
  }
  await tags.getByRole('button',{name:'PRD点评',exact:true}).click()
  await page.getByRole('textbox',{name:'问题或待点评文本'}).fill('RAG 是什么？请简洁回答。')
  const request=page.waitForRequest(r=>r.url().endsWith('/chat')&&r.method()==='POST')
  await page.getByRole('button',{name:'发送问题'}).click()
  expect((await request).postDataJSON().skill).toBe('prd_review')
  await expect(page.locator('.message.assistant .message-actions')).toBeVisible({timeout:100000})
  await page.getByRole('button',{name:/来源与过程/}).click()
  await expect(page.locator('.evidence')).toContainText('标签指定工作流，跳过语义意图识别')
  await expect(page.locator('.message.assistant .message-role')).toContainText('PRD 点评')
  await page.screenshot({path:'../data/qa-workflow-labels.png'})
  await tags.getByRole('button',{name:'PRD点评',exact:true}).click()
  await expect(tags.getByRole('button',{name:'PRD点评',exact:true})).toHaveAttribute('aria-pressed','false')
  await page.getByRole('textbox',{name:'问题或待点评文本'}).fill('帮我规划一天的 RAG 入门计划，用三行即可。')
  const requestAuto=page.waitForRequest(r=>r.url().endsWith('/chat')&&r.method()==='POST')
  await page.getByRole('button',{name:'发送问题'}).click()
  expect((await requestAuto).postDataJSON().skill).toBeNull()
  await expect(page.locator('.message.assistant').last().locator('.message-actions')).toBeVisible({timeout:100000})
  await expect(page.locator('.message.assistant .message-role').last()).toContainText('学习路径')
  await expect(page.locator('.evidence')).toContainText('意图识别')
})
