import AppKit
import CoreGraphics
import Foundation

// Production exports share paths traced from the creator-approved image.
// No inference, re-lettering, or independent redraw occurs between variants.
let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let source = URL(fileURLWithPath: CommandLine.arguments[2])
let fm = FileManager.default
func directory(_ relative: String) -> URL {
    let url = root.appendingPathComponent(relative)
    try! fm.createDirectory(at: url, withIntermediateDirectories: true)
    return url
}
let brand = directory("brand")
let assets = directory("brand/assets")
let web = directory("brand/web")
let layouts = directory("brand/canva")
let catalog = directory("app/Clipco/Assets.xcassets")
let appIcons = directory("app/Clipco/Assets.xcassets/AppIcon.appiconset")
let markImages = directory("app/Clipco/Assets.xcassets/ClipcoMark.imageset")
let horizontalImages = directory("app/Clipco/Assets.xcassets/ClipcoLogo.imageset")
let sourceFolder = directory("brand/source")
if !fm.fileExists(atPath: sourceFolder.appendingPathComponent("approved-logo.png").path) {
    try! fm.copyItem(at: source, to: sourceFolder.appendingPathComponent("approved-logo.png"))
}
let rep = NSBitmapImageRep(data: try! Data(contentsOf: source))!
let w = rep.pixelsWide, h = rep.pixelsHigh, stride = w + 1
var solid = [Bool](repeating: false, count: w * h)
for y in 0..<h { for x in 0..<w {
    solid[y*w+x] = rep.colorAt(x: x, y: y)!.alphaComponent >= 0.5
} }
func has(_ x: Int, _ y: Int) -> Bool {
    x >= 0 && x < w && y >= 0 && y < h && solid[y*w+x]
}
var next = [Int: [Int]]()
func edge(_ x1: Int, _ y1: Int, _ x2: Int, _ y2: Int) {
    next[y1*stride+x1, default: []].append(y2*stride+x2)
}
for y in 0..<h { for x in 0..<w where has(x,y) {
    if !has(x,y-1) { edge(x,y,x+1,y) }
    if !has(x+1,y) { edge(x+1,y,x+1,y+1) }
    if !has(x,y+1) { edge(x+1,y+1,x,y+1) }
    if !has(x-1,y) { edge(x,y+1,x,y) }
} }
func point(_ key: Int) -> CGPoint { CGPoint(x: key % stride, y: key / stride) }
func area(_ points: [CGPoint]) -> Double {
    var sum = 0.0
    for i in points.indices {
        let a = points[i], b = points[(i+1) % points.count]
        sum += Double(a.x*b.y - b.x*a.y)
    }
    return sum / 2
}
func simplify(_ points: [CGPoint], _ tolerance: CGFloat = 1.25) -> [CGPoint] {
    guard points.count > 2 else { return points }
    let a = points.first!, b = points.last!
    let dx = b.x-a.x, dy = b.y-a.y, length = hypot(dx,dy)
    var maxDistance: CGFloat = 0, index = 0
    for i in 1..<(points.count-1) {
        let p = points[i]
        let distance = length == 0 ? hypot(p.x-a.x,p.y-a.y)
            : abs(dy*p.x-dx*p.y+b.x*a.y-b.y*a.x)/length
        if distance > maxDistance { maxDistance = distance; index = i }
    }
    if maxDistance <= tolerance { return [a,b] }
    return Array(simplify(Array(points[...index]), tolerance).dropLast())
        + simplify(Array(points[index...]), tolerance)
}
var contours = [[CGPoint]]()
while let start = next.keys.min() {
    var key = start, points = [CGPoint](), count = 0
    repeat {
        points.append(point(key))
        guard var successors = next[key], !successors.isEmpty else { break }
        let following = successors.removeFirst()
        if successors.isEmpty { next.removeValue(forKey:key) } else { next[key] = successors }
        key = following; count += 1
    } while key != start && count < 100000
    if points.count > 3 && abs(area(points)) > 25 {
        let halfway = points.count / 2
        let smooth = Array(simplify(Array(points[...halfway])).dropLast())
            + Array(simplify(Array(points[halfway...]) + [points[0]]).dropLast())
        contours.append(smooth)
    }
}
func smooth(_ polygon: [CGPoint], _ i: Int) -> Bool {
    let n = polygon.count
    let a = polygon[(i+n-1)%n], b = polygon[i], c = polygon[(i+1)%n]
    let u = CGPoint(x:b.x-a.x,y:b.y-a.y), v = CGPoint(x:c.x-b.x,y:c.y-b.y)
    let l = hypot(u.x,u.y), r = hypot(v.x,v.y)
    return l > 0 && r > 0 && max(l,r)/min(l,r) < 3 && (u.x*v.x+u.y*v.y)/(l*r) > 0.7071
}
func controls(_ polygon: [CGPoint], _ i: Int) -> (CGPoint, CGPoint) {
    let n = polygon.count, j = (i+1)%n
    let a = polygon[i], b = polygon[j]
    let prev = polygon[(i+n-1)%n], following = polygon[(j+1)%n]
    let c1 = smooth(polygon,i) ? CGPoint(x:a.x+(b.x-prev.x)/6,y:a.y+(b.y-prev.y)/6)
        : CGPoint(x:a.x+(b.x-a.x)/3,y:a.y+(b.y-a.y)/3)
    let c2 = smooth(polygon,j) ? CGPoint(x:b.x-(following.x-a.x)/6,y:b.y-(following.y-a.y)/6)
        : CGPoint(x:b.x-(b.x-a.x)/3,y:b.y-(b.y-a.y)/3)
    return (c1,c2)
}
struct Artwork {
    var polygons: [[CGPoint]]
    var bounds: CGRect {
        polygons.flatMap{$0}.reduce(CGRect.null) { $0.union(CGRect(origin:$1,size:.zero)) }
    }
    var path: CGPath {
        let path = CGMutablePath()
        for polygon in polygons {
            path.move(to: polygon[0])
            for i in polygon.indices {
                let j = (i+1)%polygon.count
                if smooth(polygon,i) || smooth(polygon,j) {
                    let (c1,c2) = controls(polygon,i)
                    path.addCurve(to:polygon[j],control1:c1,control2:c2)
                } else { path.addLine(to:polygon[j]) }
            }
            path.closeSubpath()
        }
        return path
    }
}
let mark = Artwork(polygons: contours.filter { $0.map(\.y).max()! < CGFloat(h)*0.7 })
let word = Artwork(polygons: contours.filter { $0.map(\.y).min()! >= CGFloat(h)*0.7 })
precondition(!mark.polygons.isEmpty && !word.polygons.isEmpty)
struct Placement { var art: Artwork; var rect: CGRect }
func fit(_ art: Artwork, _ rect: CGRect) -> Placement {
    let ratio = min(rect.width/art.bounds.width, rect.height/art.bounds.height)
    let size = CGSize(width:art.bounds.width*ratio,height:art.bounds.height*ratio)
    return Placement(art:art,rect:CGRect(x:rect.midX-size.width/2,y:rect.midY-size.height/2,width:size.width,height:size.height))
}
let ink = NSColor(srgbRed: 0.055, green: 0.051, blue: 0.047, alpha: 1)
let paper = NSColor(srgbRed: 0.97, green: 0.965, blue: 0.95, alpha: 1)
func draw(_ placements: [Placement], _ color: NSColor, _ ctx: CGContext) {
    ctx.setFillColor(color.cgColor)
    for p in placements {
        ctx.saveGState()
        ctx.translateBy(x:p.rect.minX,y:p.rect.minY)
        ctx.scaleBy(x:p.rect.width/p.art.bounds.width,y:p.rect.height/p.art.bounds.height)
        ctx.translateBy(x:-p.art.bounds.minX,y:-p.art.bounds.minY)
        ctx.addPath(p.art.path); ctx.drawPath(using:.eoFill)
        ctx.restoreGState()
    }
}
func svg(_ name: String, _ width: Int, _ height: Int, _ placements: [Placement], _ white: Bool) {
    func number(_ n: CGFloat) -> String { String(format:"%.2f",Double(n)) }
    let paths = placements.map { p -> String in
        let commands = p.art.polygons.map { polygon in
            var d = "M" + number(polygon[0].x) + "," + number(polygon[0].y)
            for i in polygon.indices {
                let j = (i+1)%polygon.count, p = polygon[j]
                if smooth(polygon,i) || smooth(polygon,j) {
                    let (c1,c2) = controls(polygon,i)
                    d += " C" + number(c1.x)+","+number(c1.y)+" "+number(c2.x)+","+number(c2.y)+" "+number(p.x)+","+number(p.y)
                } else { d += " L"+number(p.x)+","+number(p.y) }
            }
            return d + " Z"
        }.joined(separator:" ")
        let transform = "translate(\(number(p.rect.minX)) \(number(p.rect.minY))) scale(\(number(p.rect.width/p.art.bounds.width)) \(number(p.rect.height/p.art.bounds.height))) translate(\(number(-p.art.bounds.minX)) \(number(-p.art.bounds.minY)))"
        return "<path fill-rule=\"evenodd\" transform=\"\(transform)\" d=\"\(commands)\"/>"
    }.joined(separator:"\n")
    let value = "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 \(width) \(height)\" width=\"\(width)\" height=\"\(height)\" role=\"img\" aria-label=\"Clipco\"><g fill=\"\(white ? "#FFFFFF" : "#0E0D0C")\">\n\(paths)\n</g></svg>\n"
    try! value.write(to:assets.appendingPathComponent(name+".svg"),atomically:true,encoding:.utf8)
}
func png(_ url: URL, _ width: Int, _ height: Int, _ render: (CGContext)->Void) {
    let ctx = CGContext(data:nil,width:width,height:height,bitsPerComponent:8,bytesPerRow:width*4,
        space:CGColorSpace(name:CGColorSpace.sRGB)!,bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.translateBy(x:0,y:CGFloat(height)); ctx.scaleBy(x:1,y:-1)
    render(ctx)
    let bitmap = NSBitmapImageRep(cgImage:ctx.makeImage()!)
    try! bitmap.representation(using:.png,properties:[:])!.write(to:url)
}
func pdf(_ url: URL, _ width: Int, _ height: Int, _ pages: [(CGContext)->Void]) {
    var box = CGRect(x:0,y:0,width:width,height:height)
    let ctx = CGContext(url as CFURL,mediaBox:&box,nil)!
    for page in pages {
        ctx.beginPDFPage(nil); ctx.saveGState()
        ctx.translateBy(x:0,y:CGFloat(height)); ctx.scaleBy(x:1,y:-1)
        page(ctx); ctx.restoreGState(); ctx.endPDFPage()
    }
    ctx.closePDF()
}
func background(_ ctx: CGContext, _ color: NSColor, _ w: Int, _ h: Int) {
    ctx.setFillColor(color.cgColor);ctx.fill(CGRect(x:0,y:0,width:w,height:h))
}
func text(_ string: String, _ x: CGFloat, _ y: CGFloat, _ size: CGFloat, _ color: NSColor,
          _ ctx: CGContext, _ weight: NSFont.Weight = .regular, _ width: CGFloat = 1300) {
    let ns = NSGraphicsContext(cgContext:ctx,flipped:true)
    NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current = ns
    let style = NSMutableParagraphStyle();style.lineBreakMode = .byWordWrapping
    (string as NSString).draw(in:CGRect(x:x,y:y,width:width,height:size*5),withAttributes:[
        .font:NSFont.systemFont(ofSize:size,weight:weight),.foregroundColor:color,.paragraphStyle:style])
    NSGraphicsContext.restoreGraphicsState()
}
let variants: [(String,Int,Int,[Placement])] = [
    ("mark",1024,1024,[fit(mark,CGRect(x:128,y:80,width:768,height:864))]),
    ("stacked",1200,1400,[fit(mark,CGRect(x:215,y:90,width:770,height:885)),fit(word,CGRect(x:120,y:1050,width:960,height:300))]),
    ("horizontal",1800,600,[fit(mark,CGRect(x:60,y:45,width:440,height:510)),fit(word,CGRect(x:610,y:150,width:1110,height:300))]),
    ("wordmark",1600,560,[fit(word,CGRect(x:80,y:60,width:1440,height:440))])
]
for (name,width,height,placements) in variants {
    let logoPages: [(CGContext)->Void] = [false,true].map { white in
        { ctx in
            ctx.scaleBy(x:0.75,y:0.75)
            background(ctx,white ? ink : paper,width,height)
            draw(placements,white ? .white : ink,ctx)
        }
    }
    pdf(layouts.appendingPathComponent("clipco-"+name+"-variations.pdf"),width*3/4,height*3/4,logoPages)
    for white in [false,true] {
        let filename = "clipco-\(name)-\(white ? "white" : "black")"
        svg(filename,width,height,placements,white)
        png(assets.appendingPathComponent(filename+".png"),width,height) { draw(placements,white ? .white : ink,$0) }
    }
}
let iconSizes = [16,32,64,128,256,512,1024]
for size in iconSizes {
    png(appIcons.appendingPathComponent("icon-\(size).png"),size,size) { ctx in
        let s = CGFloat(size)/1024
        ctx.scaleBy(x:s,y:s)
        let tile = CGRect(x:50,y:50,width:924,height:924)
        ctx.setFillColor(paper.cgColor)
        ctx.addPath(CGPath(roundedRect:tile,cornerWidth:202,cornerHeight:202,transform:nil));ctx.fillPath()
        draw([fit(mark,CGRect(x:218,y:174,width:588,height:676))],ink,ctx)
    }
}
var iconEntries = [[String:String]]()
for size in [16,32,128,256,512] { for scale in [1,2] {
    iconEntries.append(["idiom":"mac","size":"\(size)x\(size)","scale":"\(scale)x","filename":"icon-\(size*scale).png"])
} }
func json(_ value: Any, _ url: URL) {
    try! JSONSerialization.data(withJSONObject:value,options:[.prettyPrinted,.sortedKeys]).write(to:url)
}
json(["images":iconEntries,"info":["author":"xcode","version":1]],appIcons.appendingPathComponent("Contents.json"))
json(["info":["author":"xcode","version":1]],catalog.appendingPathComponent("Contents.json"))
for (folder,name,index) in [(markImages,"ClipcoMark",0),(horizontalImages,"ClipcoLogo",2)] {
    let (_,width,height,placements) = variants[index]
    pdf(folder.appendingPathComponent(name+".pdf"),width,height,[{draw(placements,ink,$0)}])
    json(["images":[["filename":name+".pdf","idiom":"universal"]],"info":["author":"xcode","version":1],
        "properties":["preserves-vector-representation":true,"template-rendering-intent":"template"]],folder.appendingPathComponent("Contents.json"))
}
for size in [16,32,48,180,192,512] {
    png(web.appendingPathComponent("clipco-icon-\(size).png"),size,size) {ctx in
        background(ctx,paper,size,size)
        draw([fit(mark,CGRect(x:CGFloat(size)*0.2,y:CGFloat(size)*0.14,width:CGFloat(size)*0.6,height:CGFloat(size)*0.72))],ink,ctx)
    }
}
let favicon = try! String(contentsOf:assets.appendingPathComponent("clipco-mark-black.svg"),encoding:.utf8)
let adaptive = favicon.replacingOccurrences(of:"<g fill=",with:"<style>g{fill:#0E0D0C}@media(prefers-color-scheme:dark){g{fill:#FFFFFF}}</style><g fill=")
try! adaptive.write(to:web.appendingPathComponent("favicon.svg"),atomically:true,encoding:.utf8)
json(["name":"Clipco","short_name":"Clipco","icons":[
    ["src":"clipco-icon-192.png","sizes":"192x192","type":"image/png","purpose":"any"],
    ["src":"clipco-icon-512.png","sizes":"512x512","type":"image/png","purpose":"any"]],
    "theme_color":"#0E0D0C","background_color":"#F7F6F2","display":"standalone"],web.appendingPathComponent("site.webmanifest"))
let boardPages: [(CGContext)->Void] = [
    {ctx in
        background(ctx,paper,1920,1080)
        draw([fit(mark,CGRect(x:1120,y:170,width:620,height:740))],ink,ctx)
        draw([fit(word,CGRect(x:140,y:275,width:790,height:255))],ink,ctx)
        text("Brand assets",145,610,46,ink,ctx,.medium)
        text("Approved identity for the Mac app,\nwebsite and marketing",145,690,32,ink,ctx,.regular,800)
    },
    {ctx in
        background(ctx,paper,1920,1080)
        text("The mark",100,75,42,ink,ctx,.semibold)
        draw([fit(mark,CGRect(x:130,y:200,width:660,height:750))],ink,ctx)
        text("A geometric C with a play triangle\nformed by the space between its facets",990,370,44,ink,ctx,.medium,780)
        text("Use the mark alone for app icons, favicons\nand compact brand placements",990,590,28,ink,ctx,.regular,780)
    },
    {ctx in
        background(ctx,paper,1920,1080);text("Stacked logo",100,75,42,ink,ctx,.semibold)
        draw([fit(mark,CGRect(x:615,y:180,width:690,height:600)),fit(word,CGRect(x:530,y:820,width:860,height:200))],ink,ctx)
    },
    {ctx in
        background(ctx,paper,1920,1080);text("Horizontal logo",100,75,42,ink,ctx,.semibold)
        draw([fit(mark,CGRect(x:200,y:310,width:410,height:470)),fit(word,CGRect(x:730,y:380,width:990,height:270))],ink,ctx)
        text("Website navigation, banners and wide placements",200,910,28,ink,ctx)
    },
    {ctx in
        background(ctx,ink,1920,1080);text("White versions",100,75,42,.white,ctx,.semibold)
        draw([fit(mark,CGRect(x:160,y:270,width:400,height:520)),fit(word,CGRect(x:700,y:365,width:1050,height:320))],.white,ctx)
        text("White assets keep the same paths for use on dark backgrounds",100,930,28,.white,ctx)
    },
    {ctx in
        background(ctx,paper,1920,1080);text("App and web icons",100,75,42,ink,ctx,.semibold)
        for (i,size) in [64,128,256,512].enumerated() {
            let x = CGFloat(120 + i*450)
            draw([fit(mark,CGRect(x:x,y:300,width:330,height:460))],ink,ctx)
            text("\(size) px",x,815,26,ink,ctx)
        }
        text("The icon contains only the mark",100,960,28,ink,ctx)
    },
    {ctx in
        background(ctx,paper,1920,1080);text("Logo usage",100,75,42,ink,ctx,.semibold)
        text("Keep the proportions and central play triangle",100,250,44,ink,ctx,.medium)
        text("Leave clear space of at least one quarter of the mark's width.\nUse black on light backgrounds and white on dark backgrounds.\nKeep the logo clear of busy photography.\nUse the mark alone below 120 px or when the name appears nearby.",100,380,32,ink,ctx,.regular,1650)
        text("Website and marketing sizes",100,720,38,ink,ctx,.medium)
        text("Website hero 1440 × 900   /   Social link preview 1200 × 630\nSquare post 1080 × 1080   /   Portrait post 1080 × 1350\nStory 1080 × 1920   /   Video thumbnail 1280 × 720",100,805,28,ink,ctx,.regular,1650)
    }
]
pdf(layouts.appendingPathComponent("clipco-brand-library.pdf"),1920,1080,boardPages)
for (i,page) in boardPages.enumerated() { png(layouts.appendingPathComponent("brand-page-\(i+1).png"),1920,1080,page) }
struct Template { let name: String; let width: Int; let height: Int; let render: (CGContext)->Void }
let templates: [Template] = [
    Template(name:"website-hero",width:1440,height:900,render:{ctx in
        background(ctx,paper,1440,900)
        draw([fit(mark,CGRect(x:75,y:52,width:48,height:58)),fit(word,CGRect(x:146,y:64,width:190,height:46))],ink,ctx)
        text("Find the footage\nthat fits your idea",80,265,76,ink,ctx,.bold,825)
        text("Prepare local footage context\nfor your editing agent.",85,520,32,ink,ctx,.regular,760)
        draw([fit(mark,CGRect(x:955,y:260,width:370,height:435))],ink,ctx)
        text("Clipco for Mac",85,770,22,ink,ctx,.medium)
    }),
    Template(name:"social-link-preview",width:1200,height:630,render:{ctx in
        background(ctx,ink,1200,630)
        draw([fit(word,CGRect(x:65,y:55,width:365,height:110))],.white,ctx)
        text("Your footage.\nReady for your agent.",65,250,58,.white,ctx,.bold,750)
        draw([fit(mark,CGRect(x:875,y:180,width:245,height:305))],.white,ctx)
        text("Local footage context for Mac",65,535,25,.white,ctx)
    }),
    Template(name:"square-post",width:1080,height:1080,render:{ctx in
        background(ctx,paper,1080,1080)
        draw([fit(word,CGRect(x:80,y:55,width:340,height:115))],ink,ctx)
        text("Find the shot\nyou had in mind",80,240,76,ink,ctx,.bold,920)
        draw([fit(mark,CGRect(x:610,y:480,width:330,height:400))],ink,ctx)
        text("Prepare your raw footage\nfor your editing agent.",80,780,32,ink,ctx,.regular,510)
    }),
    Template(name:"portrait-post",width:1080,height:1350,render:{ctx in
        background(ctx,ink,1080,1350)
        draw([fit(word,CGRect(x:80,y:55,width:350,height:120))],.white,ctx)
        text("Give your agent\nfootage context",80,270,76,.white,ctx,.bold,920)
        draw([fit(mark,CGRect(x:360,y:610,width:430,height:510))],.white,ctx)
        text("Clipco for Mac",80,1190,28,.white,ctx)
    }),
    Template(name:"story",width:1080,height:1920,render:{ctx in
        background(ctx,paper,1080,1920)
        draw([fit(word,CGRect(x:90,y:270,width:350,height:120))],ink,ctx)
        text("Your raw footage,\nready to search",90,530,78,ink,ctx,.bold,900)
        draw([fit(mark,CGRect(x:310,y:910,width:470,height:560))],ink,ctx)
        text("Local context for your editing agent",90,1600,30,ink,ctx,.regular,900)
    }),
    Template(name:"video-thumbnail",width:1280,height:720,render:{ctx in
        background(ctx,ink,1280,720)
        draw([fit(word,CGRect(x:65,y:50,width:345,height:110))],.white,ctx)
        text("Find footage\nwith context",65,270,80,.white,ctx,.bold,800)
        draw([fit(mark,CGRect(x:900,y:210,width:285,height:340))],.white,ctx)
    })
]
for t in templates {
    pdf(layouts.appendingPathComponent("clipco-\(t.name).pdf"),t.width,t.height,[t.render])
    png(layouts.appendingPathComponent("clipco-\(t.name).png"),t.width,t.height,t.render)
}
let pathData: [String:Any] = ["source":"source/approved-logo.png","threshold":0.5,"simplification_px":1.25,
    "mark_contours":mark.polygons.count,"wordmark_contours":word.polygons.count]
json(pathData,brand.appendingPathComponent("generation.json"))
print("Created black/white SVG and PNG variants, app catalog, web icons, eleven Canva PDFs. Mark contours: \(mark.polygons.count), wordmark contours: \(word.polygons.count)")
