window.DEMO_DATA = {
  asOf: "2026-09-21",
  competitors: [
    {id:1,name:"Notion",initial:"N",domain:"notion.so",description:"A connected workspace for knowledge, documents and projects.",status:"Reviewed",sources:4,checked:"Sep 21, 09:42",facts:["Collaborative documents","Knowledge base","AI-assisted search"],price:"Plus · 12 USD / user / month"},
    {id:2,name:"Linear",initial:"L",domain:"linear.app",description:"Product planning and issue tracking for software teams.",status:"Needs review",sources:4,checked:"Sep 21, 09:35",facts:[],price:null},
    {id:3,name:"飞书",initial:"飞",domain:"feishu.cn",description:"An integrated workspace for communication and collaboration.",status:"Reviewed",sources:2,checked:"Sep 20, 16:10",facts:["Shared documents","Team messaging"],price:null}
  ],
  signals: [
    {id:1,cid:1,category:"Pricing",type:"MODIFIED",title:"Plus annual billing updated",old:"10 USD",value:"12 USD / user / month",date:"2026-09-21",evidence:"Demo evidence: Plus plan costs $12 per user / month, billed annually.",path:"/pricing"},
    {id:2,cid:1,category:"Feature",type:"ADDED",title:"Workspace search expanded",old:"",value:"Enterprise search across connected content",date:"2026-09-20",evidence:"Demo evidence: Search connected knowledge from one workspace.",path:"/product"},
    {id:3,cid:2,category:"Source",type:"UNCOMPARABLE",title:"Fact extraction awaiting verification",old:"",value:"Real fact extraction provider is not connected.",date:"2026-09-20",evidence:"Demo audit: Page fetched; structured fact extraction skipped.",path:"/"},
    {id:4,cid:3,category:"Feature",type:"ADDED",title:"Shared document capability recorded",old:"",value:"Collaborative editing",date:"2026-09-19",evidence:"Demo evidence: Teams can edit shared documents.",path:"/product"},
    {id:5,cid:1,category:"Product",type:"REMOVED",title:"Legacy product note removed",old:"Legacy release note",value:"No longer present in the latest demo snapshot",date:"2026-09-18",evidence:"Demo comparison: Previously recorded release note is absent.",path:"/releases"},
    {id:6,cid:3,category:"Positioning",type:"MODIFIED",title:"Workspace positioning updated",old:"Team collaboration",value:"Connected team workspace",date:"2026-09-17",evidence:"Demo evidence: A connected workspace for teams.",path:"/"}
  ],
  reports: [
    {id:1,cid:1,title:"Notion · Change briefing",date:"Sep 21, 09:42",type:"Change report",changes:3},
    {id:2,cid:2,title:"Linear · Initial profile",date:"Sep 21, 09:35",type:"Initial profile",changes:1},
    {id:3,cid:3,title:"飞书 · Change briefing",date:"Sep 20, 16:10",type:"Change report",changes:2}
  ],
  runs: [
    {id:104,cid:1,status:"COMPLETED",provider:"Fixture",tools:7},
    {id:103,cid:2,status:"COMPLETED_WITH_WARNINGS",provider:"Serper preview",tools:6},
    {id:102,cid:3,status:"COMPLETED",provider:"Fixture",tools:7}
  ]
};
