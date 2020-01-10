package Demo.Main;

import javax.imageio.ImageIO;
import java.applet.Applet;
import java.applet.AudioClip;
import java.awt.*;
import java.io.IOException;

/**
 * Created by jassiboy on 2/26/2017.
 */
public class Resources {
    public static Image welcomeImage;
    public static Image EndstageImage;
    public static Image background1Image;
    public static Image winterImage;
    public static Image Stage3Image;
    public static Image background11Image;
    public static Image arrowImage;
    public static Image logImage;
    public static Image heliImage;
    public static Image firebollImage;
    public static Image birdImage1;
    public static Image birdImage2;
    public static Image mushroomImage;
    public static Image grassImage;
    public static Image dragonImage1;
    public static Image dragonImage2;
    public static Image dragonImage3;
    public static Image dragonImage4;
    public static Image dragonattack;

    public static AudioClip flapAudio = null;
    public static AudioClip singAudio = null;




    public static void load() {
        try {
            Resources.logImage = ImageIO.read(Game.class.getResource("../Resources/images/cutmypic (1).png"));
            Resources.heliImage = ImageIO.read(Game.class.getResource("../Resources/images/heli.png"));
            Resources.firebollImage = ImageIO.read(Game.class.getResource("../Resources/images/fireboll.png"));
            Resources.background1Image = ImageIO.read(Game.class.getResource("../Resources/images/cover.png"));
            Resources.winterImage = ImageIO.read(Game.class.getResource("../Resources/images/winter.jpg"));
            Resources.Stage3Image = ImageIO.read(Game.class.getResource("../Resources/images/stage3Img.png"));
            Resources.mushroomImage = ImageIO.read(Game.class.getResource("../Resources/images/Mushroom1.png"));
            Resources.grassImage = ImageIO.read(Game.class.getResource("../Resources/images/grass.png"));
            Resources.welcomeImage = ImageIO.read(Game.class.getResource("../Resources/images/Menuimage.jpg"));
            Resources.EndstageImage = ImageIO.read(Game.class.getResource("../Resources/images/Endstage.jpg"));
            Resources.arrowImage = ImageIO.read(Game.class.getResource("../Resources/images/selectorr.png"));
            Resources.birdImage1 = ImageIO.read(Game.class.getResource("../Resources/images/birdf1.png"));
            Resources.birdImage2 = ImageIO.read(Game.class.getResource("../Resources/images/birdf2.png"));
            Resources.dragonImage1 = ImageIO.read(Game.class.getResource("../Resources/images/frame-1.png"));
            Resources.dragonImage2 = ImageIO.read(Game.class.getResource("../Resources/images/frame-2.png"));
            Resources.dragonImage3 = ImageIO.read(Game.class.getResource("../Resources/images/frame-3.png"));
            Resources.dragonImage4 = ImageIO.read(Game.class.getResource("../Resources/images/frame-4.png"));
            Resources.dragonattack = ImageIO.read(Game.class.getResource("../Resources/images/frame-5.png"));
            Resources.flapAudio = Applet.newAudioClip(Game.class.getResource("../Resources/audio/ting.wav"));
            //Resources.singAudio = Applet.newAudioClip(Game.class.getResource("../Resources/audio/sing.m4a"));

        } catch (IOException e) {
            System.out.println("Images not loaded");
        }
    }

}
