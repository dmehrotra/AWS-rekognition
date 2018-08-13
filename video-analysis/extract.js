var Promise = require("bluebird");
var ffmpeg = require('ffmpeg');
var file = process.argv[2]
console.log(file)

var getvideo = new ffmpeg(file);
getvideo.then(function (video) {
	extractFrames(video).then(function(frames){
		console.log(frames)
	})
})
function extractFrames(video){
	return new Promise(function(resolve,reject){
		video.fnExtractFrameToJPG('frames', {
			start_time : 6,
			duration_time: 1,
			frame_rate : 3,
			file_name : 'r'
		}, function (error, files) {
			if (!error){
				resolve(files);
			}else{reject(error)}
		});
	})
}
